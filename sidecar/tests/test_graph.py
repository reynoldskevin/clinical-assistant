"""Acceptance tests for ticket 49 — LangGraph supervisor + two worker nodes.

Locked contract (orchestrator-authored, TDD). The implementer writes production
code in sidecar/graph.py (+ nothing else required) to satisfy these; test files
must NOT be edited.

Everything here runs offline with STUBBED workers/tools — no Claude, no VLM, no
network, no keys. The graph is REAL LangGraph; only the leaf tool calls (extract,
retrieve) are injected stubs so routing, handoff logging, correlation-id
propagation, the WorkerResult contract, and the verification gate can be asserted
deterministically.
"""

import operator

import pytest

from graph import (
    WorkerResult,
    build_supervisor_graph,
    make_default_finalizer,
    route_workers,
    run_supervisor,
)


# --- stubs --------------------------------------------------------------------

class RecordingExtractor:
    """Stub intake-extractor tool: records how the worker invoked it."""

    def __init__(self, citations=None, payload=None):
        self.calls = []
        self._citations = citations or ["Lab Report — Result"]
        self._payload = payload or {"test_name": "HbA1c", "value": "5.4"}

    def __call__(self, *, question, pid, correlation_id):
        self.calls.append({"question": question, "pid": pid, "correlation_id": correlation_id})
        return {"citations": list(self._citations), "payload": dict(self._payload)}


class RecordingRetriever:
    """Stub evidence-retriever tool: records how the worker invoked it."""

    def __init__(self, citations=None, payload=None):
        self.calls = []
        self._citations = citations or [
            "Anticoagulation Management (Synthetic Guideline) — Warfarin INR Monitoring"
        ]
        self._payload = payload or {"chunks": 1}

    def __call__(self, *, question, pid, correlation_id):
        self.calls.append({"question": question, "pid": pid, "correlation_id": correlation_id})
        return {"citations": list(self._citations), "payload": dict(self._payload)}


# Questions engineered to trigger the rule-based router deterministically.
MIXED_Q = "Extract the uploaded lab report and show the guideline evidence supporting it."
EXTRACT_ONLY_Q = "Extract the values from the uploaded lab report document."
EVIDENCE_ONLY_Q = "What guideline evidence and recommendations support this management plan?"


def _run(question, *, extractor=None, retriever=None, cid="cid-123", gate=None, finalizer=None):
    extractor = extractor or RecordingExtractor()
    retriever = retriever or RecordingRetriever()
    state = run_supervisor(
        question,
        pid=42,
        correlation_id=cid,
        extractor=extractor,
        retriever=retriever,
        gate=gate,
        finalizer=finalizer,
    )
    return state, extractor, retriever


# --- it's a real LangGraph graph ---------------------------------------------

def test_build_supervisor_graph_is_a_real_langgraph_app_with_the_four_nodes():
    app = build_supervisor_graph(extractor=RecordingExtractor(), retriever=RecordingRetriever())
    # A compiled LangGraph app, not a hand-rolled object.
    assert type(app).__module__.startswith("langgraph")
    assert hasattr(app, "invoke")
    nodes = set(app.get_graph().nodes)
    for name in ("supervisor", "intake_extractor", "evidence_retriever", "finalize"):
        assert name in nodes


# --- routing ------------------------------------------------------------------

def test_route_workers_rule_based_selection():
    assert route_workers(MIXED_Q) == ["intake_extractor", "evidence_retriever"]
    assert route_workers(EXTRACT_ONLY_Q) == ["intake_extractor"]
    assert route_workers(EVIDENCE_ONLY_Q) == ["evidence_retriever"]


def test_mixed_question_routes_through_both_workers_in_order():
    state, extractor, retriever = _run(MIXED_Q)
    workers = [wr["worker"] for wr in state["worker_results"]]
    assert workers == ["intake_extractor", "evidence_retriever"]
    assert len(extractor.calls) == 1
    assert len(retriever.calls) == 1


def test_extraction_only_question_routes_to_one_worker():
    state, extractor, retriever = _run(EXTRACT_ONLY_Q)
    workers = [wr["worker"] for wr in state["worker_results"]]
    assert workers == ["intake_extractor"]
    assert len(extractor.calls) == 1
    assert retriever.calls == []


def test_retrieval_only_question_routes_to_one_worker():
    state, extractor, retriever = _run(EVIDENCE_ONLY_Q)
    workers = [wr["worker"] for wr in state["worker_results"]]
    assert workers == ["evidence_retriever"]
    assert len(retriever.calls) == 1
    assert extractor.calls == []


# --- handoffs logged + inspectable -------------------------------------------

def test_routing_log_records_each_supervisor_decision_and_worker_return():
    state, _, _ = _run(MIXED_Q)
    log = state["routing_log"]
    # Each hop is an inspectable {from, to, correlation_id} record.
    for entry in log:
        assert set(entry) >= {"from", "to", "correlation_id"}
    # The supervisor's routing decisions, in order, end at finalize.
    supervisor_decisions = [e["to"] for e in log if e["from"] == "supervisor"]
    assert supervisor_decisions == ["intake_extractor", "evidence_retriever", "finalize"]
    # Each worker hands control back to the supervisor.
    worker_returns = [e["from"] for e in log if e["to"] == "supervisor"]
    assert worker_returns == ["intake_extractor", "evidence_retriever"]


# --- correlation-id propagation ----------------------------------------------

def test_correlation_id_propagates_to_every_hop_and_tool_call():
    cid = "corr-abc-999"
    state, extractor, retriever = _run(MIXED_Q, cid=cid)
    # every routing-log hop carries it
    assert all(e["correlation_id"] == cid for e in state["routing_log"])
    # every worker result carries it
    assert all(wr["correlation_id"] == cid for wr in state["worker_results"])
    # it reached each leaf tool invocation (the VLM/retrieval call)
    assert extractor.calls[0]["correlation_id"] == cid
    assert retriever.calls[0]["correlation_id"] == cid


def test_run_supervisor_generates_a_correlation_id_when_none_given():
    state, extractor, _ = _run(EXTRACT_ONLY_Q, cid=None)
    cid = extractor.calls[0]["correlation_id"]
    assert isinstance(cid, str) and cid  # non-empty
    assert all(wr["correlation_id"] == cid for wr in state["worker_results"])


# --- pid is session-fixed into every worker ----------------------------------

def test_pid_is_session_fixed_into_every_worker():
    state, extractor, retriever = _run(MIXED_Q)
    assert extractor.calls[0]["pid"] == 42
    assert retriever.calls[0]["pid"] == 42


# --- WorkerResult typed contract ---------------------------------------------

def test_worker_result_contract_roundtrip_and_strict():
    wr = WorkerResult(
        worker="intake_extractor",
        kind="extraction",
        correlation_id="c1",
        citations=["Lab Report — Result"],
        payload={"test_name": "HbA1c"},
    )
    dumped = wr.model_dump()
    assert WorkerResult.model_validate(dumped) == wr
    # strict: unknown fields rejected (mirrors the other sidecar contracts)
    with pytest.raises(Exception):
        WorkerResult.model_validate({**dumped, "bogus": 1})


def test_worker_results_in_state_are_valid_worker_result_dumps():
    state, _, _ = _run(MIXED_Q)
    for wr in state["worker_results"]:
        # each round-trips through the contract without loss
        assert WorkerResult.model_validate(wr).worker == wr["worker"]
        assert wr["kind"] in {"extraction", "evidence"}
        assert isinstance(wr["citations"], list)


# --- verification gate preserved through the graph ---------------------------

def test_finalize_runs_the_verification_gate_over_combined_worker_citations():
    class RecordingGate:
        def __init__(self):
            self.calls = []

        def verify(self, draft, citations, retrieved_refs, retrieved_data=None):
            self.calls.append(
                {"draft": draft, "citations": citations, "refs": set(retrieved_refs)}
            )
            return {"verdict": "pass", "flags": [], "rendered_answer": "FINAL ANSWER"}

    gate = RecordingGate()
    extractor = RecordingExtractor(citations=["Lab Report — Result"])
    retriever = RecordingRetriever(
        citations=["Anticoagulation Management (Synthetic Guideline) — Warfarin INR Monitoring"]
    )
    state, _, _ = _run(MIXED_Q, extractor=extractor, retriever=retriever, gate=gate)

    assert state["answer"] == "FINAL ANSWER"
    assert len(gate.calls) == 1
    # the gate saw BOTH workers' citations as the retrieved refs (grounding set)
    refs = gate.calls[0]["refs"]
    assert "Lab Report — Result" in refs
    assert "Anticoagulation Management (Synthetic Guideline) — Warfarin INR Monitoring" in refs


def test_default_finalizer_uses_the_real_verification_gate_and_sets_a_verdict():
    # No gate injected -> the default finalizer wires the real VerificationGate.
    state, _, _ = _run(MIXED_Q)
    assert isinstance(state["answer"], str) and state["answer"].strip() != ""
    assert state["verdict"] in {"pass", "pass_with_flags", "blocked"}


def test_make_default_finalizer_is_callable_over_state():
    fin = make_default_finalizer()
    st = {
        "worker_results": [
            {
                "worker": "evidence_retriever",
                "kind": "evidence",
                "correlation_id": "c1",
                "citations": ["Guide — Section"],
                "payload": {},
            }
        ],
        "correlation_id": "c1",
    }
    answer = fin(st)
    assert isinstance(answer, str) and answer.strip() != ""


# --- state shape uses accumulating reducers (sanity) -------------------------

def test_reducers_accumulate_rather_than_overwrite():
    # Both worker nodes append to worker_results; both + supervisor append to
    # routing_log. If the channels overwrote, we'd see only the last node's entry.
    state, _, _ = _run(MIXED_Q)
    assert len(state["worker_results"]) == 2
    assert len(state["routing_log"]) >= 4  # 3 supervisor decisions + 2 worker returns
    # operator.add is the intended reducer for these list channels
    assert operator.add([1], [2]) == [1, 2]
