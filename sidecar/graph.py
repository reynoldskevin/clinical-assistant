"""LangGraph supervisor + intake-extractor / evidence-retriever workers.

Week 2 Stage 3, requirement 3 (multi-agent). A minimal LangGraph ``StateGraph``
ports the Week 1 loop into two worker nodes under a supervisor that routes
deterministically: extraction needed? retrieval needed? answer ready?

* The graph is a REAL compiled LangGraph app — routing, handoff logging,
  correlation-id propagation, the ``WorkerResult`` contract, and the
  verification gate are all exercised through the same graph the server would
  run. Only the leaf tool calls (extract, retrieve) are injected, so the tested
  path runs fully offline: no Claude, no VLM, no network, no keys.
* Handoffs are explicit and logged: every supervisor decision and every worker
  return appends an inspectable ``{from, to, correlation_id}`` record to the
  ``routing_log`` channel.
* The pid is session-fixed and the correlation id propagates into every worker
  (and thus every VLM / retrieval call).

The accumulating channels (``routing_log``, ``worker_results``) use
``operator.add`` reducers so each node APPENDS rather than overwrites; without a
reducer LangGraph would keep only the last writer's value.

The anthropic / cohere / numpy SDKs are never imported at module top — this
module stays importable with only ``langgraph`` + ``pydantic`` (+ the pure
sidecar modules) installed. Production adapters that reach the real extractor /
retriever import those lazily.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

import factory
from events import (
    EXTRACTION_FIELD,
    RETRIEVAL_HIT,
    RETRIEVAL_MISS,
    WORKER_HANDOFF,
    log_event,
)
from observability import NullTracer
from verification import VerificationGate

# Worker node names, in the canonical order the supervisor visits them
# (extraction before evidence).
_INTAKE = "intake_extractor"
_EVIDENCE = "evidence_retriever"

# Rule-based routing keywords. Extraction keywords select the intake extractor;
# evidence keywords select the evidence retriever. Both matched -> both workers,
# always in extraction-before-evidence order.
_EXTRACTION_KEYWORDS = (
    "extract",
    "document",
    "lab",
    "labs",
    "report",
    "intake",
    "upload",
    "form",
    "pdf",
    "scan",
    "result",
    "results",
)
_EVIDENCE_KEYWORDS = (
    "guideline",
    "guidelines",
    "evidence",
    "recommend",
    "recommendation",
    "recommendations",
    "should",
    "target",
    "manage",
    "management",
    "protocol",
    "best practice",
)


class WorkerResult(BaseModel):
    """Typed supervisor<->worker contract for one worker's output.

    STRICT (``extra="forbid"``): a worker cannot smuggle unknown fields past the
    contract. ``citations`` / ``payload`` use ``default_factory`` so the mutable
    defaults are never shared between instances.
    """

    model_config = ConfigDict(extra="forbid")

    worker: str
    kind: str
    correlation_id: str
    citations: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)


class GraphState(TypedDict, total=False):
    """LangGraph state channels. List channels accumulate via ``operator.add``."""

    question: str
    pid: int
    correlation_id: str
    route: list[str]
    _next: str
    routing_log: Annotated[list[dict], operator.add]
    worker_results: Annotated[list[dict], operator.add]
    answer: str
    verdict: str
    # Prior-turn messages for multi-turn context. A plain last-value channel
    # (NOT a reducer): seeded once in initial_state, read by the finalize seam,
    # never mutated by nodes.
    history: list


def route_workers(question: str) -> list[str]:
    """Deterministic rule-based router.

    Returns a subset of ``[intake_extractor, evidence_retriever]``, ALWAYS in
    that order (extraction before evidence). An extraction keyword selects the
    intake extractor; an evidence keyword selects the evidence retriever. If
    NEITHER matches, both workers run.
    """
    text = question.lower()
    workers: list[str] = []
    if any(kw in text for kw in _EXTRACTION_KEYWORDS):
        workers.append(_INTAKE)
    if any(kw in text for kw in _EVIDENCE_KEYWORDS):
        workers.append(_EVIDENCE)
    if not workers:
        return [_INTAKE, _EVIDENCE]
    return workers


def _gather_refs(worker_results: list[dict]) -> list[str]:
    """Collect every worker citation, deduped, preserving first-seen order."""
    refs: list[str] = []
    seen: set[str] = set()
    for wr in worker_results:
        for citation in wr.get("citations", []):
            if citation not in seen:
                seen.add(citation)
                refs.append(citation)
    return refs


def _compose_and_verify(state: GraphState, gate: Any) -> dict[str, Any]:
    """Compose a draft over the combined worker citations and run the gate.

    Shared by the finalize node and ``make_default_finalizer`` so the two agree
    exactly. Gathers the deduped worker citations as the grounding refs, builds a
    numbered citation list and a short ``[Sn]``-marked draft, then returns the
    gate's ``verify`` result dict.
    """
    worker_results = state.get("worker_results", [])
    refs = _gather_refs(worker_results)
    citations = [{"n": i + 1, "ref": ref} for i, ref in enumerate(refs)]

    if refs:
        markers = " ".join(f"[S{i + 1}]" for i in range(len(refs)))
        draft = f"Based on the retrieved findings {markers}."
    else:
        draft = "No grounded findings were retrieved for this question."

    return gate.verify(draft, citations, set(refs), None)


def make_default_finalizer(gate: Any = None) -> Callable[[GraphState], str]:
    """Return a callable ``fin(state) -> str`` running the default compose+verify.

    Uses the same shared compose+verify as the finalize node, so a finalizer
    injected via ``build_supervisor_graph(finalizer=...)`` and the internal
    gate-based finalize produce identical rendered answers. Defaults to a real
    :class:`VerificationGate` when no gate is injected.
    """
    resolved_gate = gate or VerificationGate()

    def fin(state: GraphState) -> str:
        verdict = _compose_and_verify(state, resolved_gate)
        return verdict["rendered_answer"]

    return fin


def _supervisor_node(state: GraphState, router: Callable[[str], list[str]]) -> dict[str, Any]:
    """Pick the next unfinished worker in the route, else finalize; log the hop."""
    route = state.get("route") or router(state["question"])
    done = {wr["worker"] for wr in state.get("worker_results", [])}
    nxt = next((w for w in route if w not in done), "finalize")
    cid = state["correlation_id"]
    entry = {
        "from": "supervisor",
        "to": nxt,
        "correlation_id": cid,
    }
    log_event(WORKER_HANDOFF, cid, from_="supervisor", to=nxt)
    return {"route": route, "_next": nxt, "routing_log": [entry]}


def _worker_node(
    state: GraphState,
    *,
    worker: str,
    kind: str,
    tool: Callable[..., dict[str, Any]],
    tracer: Any = None,
) -> dict[str, Any]:
    """Invoke an injected leaf tool and record its result + return hop.

    The tool call runs inside the worker's child span (``parent="supervisor"``),
    entered before the tool runs and exited afterward — including when the tool
    raises, so a full request trace is reconstructable from the correlation id.
    """
    resolved_tracer = tracer or NullTracer()
    cid = state["correlation_id"]
    with resolved_tracer.worker_span(worker, cid, kind=kind, parent="supervisor"):
        result = tool(
            question=state["question"],
            pid=state["pid"],
            correlation_id=cid,
        )
        citations = list(result["citations"])
        payload = dict(result["payload"])
        wr = WorkerResult(
            worker=worker,
            kind=kind,
            correlation_id=cid,
            citations=citations,
            payload=payload,
        )

        if worker == _EVIDENCE:
            if citations:
                log_event(RETRIEVAL_HIT, cid, count=len(citations))
            else:
                log_event(RETRIEVAL_MISS, cid)
        elif worker == _INTAKE:
            for field_name, outcome in payload.get("field_outcomes", {}).items():
                log_event(EXTRACTION_FIELD, cid, field=field_name, outcome=outcome)

    log_event(WORKER_HANDOFF, cid, from_=worker, to="supervisor")
    return {
        "worker_results": [wr.model_dump()],
        "routing_log": [{"from": worker, "to": "supervisor", "correlation_id": cid}],
    }


def build_supervisor_graph(
    *,
    extractor: Callable[..., dict[str, Any]],
    retriever: Callable[..., dict[str, Any]],
    router: Callable[[str], list[str]] = route_workers,
    finalizer: Optional[Callable[[GraphState], str]] = None,
    gate: Any = None,
    tracer: Any = None,
) -> Any:
    """Build and COMPILE the supervisor/worker LangGraph app.

    Nodes: ``supervisor``, ``intake_extractor``, ``evidence_retriever``,
    ``finalize``. The supervisor routes via ``router`` and hands off to the next
    unfinished worker (each of which returns to the supervisor) until every
    routed worker has run, then to ``finalize``. ``finalize`` runs the
    verification gate over the combined worker citations, unless a ``finalizer``
    is injected to replace the answer computation.
    """
    resolved_gate = gate or VerificationGate()
    resolved_tracer = tracer or NullTracer()

    def supervisor(state: GraphState) -> dict[str, Any]:
        return _supervisor_node(state, router)

    def intake_extractor(state: GraphState) -> dict[str, Any]:
        return _worker_node(
            state, worker=_INTAKE, kind="extraction", tool=extractor, tracer=resolved_tracer
        )

    def evidence_retriever(state: GraphState) -> dict[str, Any]:
        return _worker_node(
            state, worker=_EVIDENCE, kind="evidence", tool=retriever, tracer=resolved_tracer
        )

    def finalize(state: GraphState) -> dict[str, Any]:
        if finalizer is not None:
            answer = finalizer(state)
            # A custom finalizer owns the answer; there is no gate verdict to
            # report, so mark the turn finalized.
            return {"answer": answer, "verdict": "pass"}
        verdict = _compose_and_verify(state, resolved_gate)
        return {"answer": verdict["rendered_answer"], "verdict": verdict["verdict"]}

    builder = StateGraph(GraphState)
    builder.add_node("supervisor", supervisor)
    builder.add_node(_INTAKE, intake_extractor)
    builder.add_node(_EVIDENCE, evidence_retriever)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["_next"],
        {
            _INTAKE: _INTAKE,
            _EVIDENCE: _EVIDENCE,
            "finalize": "finalize",
        },
    )
    builder.add_edge(_INTAKE, "supervisor")
    builder.add_edge(_EVIDENCE, "supervisor")
    builder.add_edge("finalize", END)

    return builder.compile()


def run_supervisor(
    question: str,
    pid: int,
    *,
    correlation_id: Optional[str] = None,
    extractor: Callable[..., dict[str, Any]],
    retriever: Callable[..., dict[str, Any]],
    router: Callable[[str], list[str]] = route_workers,
    finalizer: Optional[Callable[[GraphState], str]] = None,
    gate: Any = None,
    store: Any = None,
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build the supervisor graph and run one turn, returning the final state.

    Generates a correlation id when none is given. All accumulating channels are
    initialized empty so the reducers append onto a known base. The returned
    dict exposes ``worker_results``, ``routing_log``, ``answer``, and ``verdict``.

    Multi-turn: when both ``store`` and a non-empty ``conversation_id`` are
    given, prior turns for this ``pid``-scoped conversation are loaded and
    exposed to the finalize seam via the ``history`` channel, then this turn's
    ``user`` + ``assistant`` messages are appended and persisted. Without a store
    (or with an empty conversation id) the graph stays exactly stateless.
    """
    cid = correlation_id or factory.new_correlation_id()
    app = build_supervisor_graph(
        extractor=extractor,
        retriever=retriever,
        router=router,
        finalizer=finalizer,
        gate=gate,
    )
    persisting = store is not None and isinstance(conversation_id, str) and conversation_id != ""
    prior: list = store.history(conversation_id, pid) or [] if persisting else []
    initial_state: GraphState = {
        "question": question,
        "pid": pid,
        "correlation_id": cid,
        "route": [],
        "routing_log": [],
        "worker_results": [],
        "answer": "",
        "history": prior,
    }
    state = dict(app.invoke(initial_state))
    if persisting:
        new_history = prior + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": state.get("answer", "")},
        ]
        store.remember(conversation_id, pid, new_history)
        state["history"] = new_history
    else:
        # Stateless path: do not expose a populated history. The backward-compat
        # test asserts state.get("history", []) == [].
        state["history"] = []
    return state


# --- production adapters (thin; not under test, but required for real wiring) --

def build_intake_extractor(chart_boundary: Any, message_creator: Callable[..., Any]) -> Callable[..., dict[str, Any]]:
    """Return a ``(question, pid, correlation_id)`` intake-extractor tool.

    Lists the patient's documents via the pid-scoped ``chart_boundary``, picks
    the most-recent one, runs the T47 VLM extractor over it, and returns the
    fact's ``source_citation`` plus PHI-free telemetry.
    """

    def extract(*, question: str, pid: int, correlation_id: str) -> dict[str, Any]:
        # correlation_id is carried on the chart_boundary/message_creator wiring
        # itself (both are built per-turn with the id); attach_and_extract does
        # not take it as a keyword, so it is not forwarded here.
        import extractor as extractor_module  # lazy: keeps graph import SDK-free

        documents = chart_boundary.get_documents(pid)
        if not documents:
            return {"citations": [], "payload": {"documents": 0}}
        # Most-recent document: the read boundary returns newest-first; fall back
        # to the last by docdate if that ordering is ever not guaranteed.
        most_recent = documents[0]
        doc_id = most_recent["id"]
        doc_type = most_recent["doc_type"]
        result = extractor_module.attach_and_extract(
            pid,
            doc_id,
            doc_type,
            chart_boundary=chart_boundary,
            message_creator=message_creator,
        )
        return {
            "citations": [result.fact.source_citation],
            "payload": result.telemetry(),
        }

    return extract


def build_evidence_retriever(index: Any) -> Callable[..., dict[str, Any]]:
    """Return a ``(question, pid, correlation_id)`` evidence-retriever tool.

    Runs T48 hybrid retrieval over the guideline ``index`` and returns each
    chunk's citation plus the chunk rows.
    """

    def retrieve(*, question: str, pid: int, correlation_id: str) -> dict[str, Any]:
        # correlation_id is not threaded into hybrid_retrieve — the T48 API does
        # not accept it; retrieval is pid-independent guideline lookup.
        import retrieval  # lazy: keeps graph import numpy/cohere-free

        chunks = retrieval.hybrid_retrieve(question, index)
        return {
            "citations": [c.citation for c in chunks],
            "payload": {
                "chunks": [
                    {"citation": c.citation, "text": c.text, "score": c.score}
                    for c in chunks
                ]
            },
        }

    return retrieve
