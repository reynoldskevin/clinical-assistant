"""Runnable HTTP sidecar: POST /ask -> ClaudeAgent -> {"answer": ...}.

Stateless and single-endpoint. Every request carries a short-lived,
patient-scoped JWT (minted by OpenEMR's token.php); the sidecar forwards that
token to the OpenEMR boundary for each chart read and never sees the signing
key. No PHI is persisted here.

The request handling is split into a pure ``process_ask`` function (unit-tested,
no sockets) and a thin ``BaseHTTPRequestHandler`` that adapts it to HTTP.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import threading
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from agent import ClaudeAgent
from conversation import ConversationStore
from health import liveness, ready_response
from factory import (
    build_boundary,
    build_chart_boundary,
    build_documents_tools,
    build_encounter_tools,
    build_intake_tool,
    build_medications_tool,
    build_message_creator,
    build_results_tool,
    build_search_tool,
    build_tracer,
    new_correlation_id,
)
from observability import TraceCollector
from retrieval import build_evidence_retriever_tool, get_guideline_index
from extractor import attach_and_extract
from bbox import locate_citation_boxes
from identity_check import check_identity
from events import INGESTION_COMPLETE, INGESTION_START, log_event

from pydantic import ValidationError

# An agent-builder maps (pid, jwt) -> an object with .run(question, pid) -> str.
AgentBuilder = Callable[[int, str], Any]

# An extract-fn maps (pid, jwt, document_id, doc_type) -> a JSON-safe result dict.
ExtractFn = Callable[[int, str, int, str], dict[str, Any]]

# The closed set of document types the extractor understands (mirrors upload.php).
_DOC_TYPES = ("lab_pdf", "intake_form")

# Default Claude model for both the agent loop and the document extractor. The
# deployment can override it (e.g. a faster tier) via OE_AI_AGENT_MODEL without a
# code change; unset preserves the historical Opus default.
_DEFAULT_MODEL = "claude-opus-4-8"


def _configured_model() -> str:
    """Return the Claude model to use, honoring the OE_AI_AGENT_MODEL override."""
    return os.environ.get("OE_AI_AGENT_MODEL") or _DEFAULT_MODEL


def _extract_model() -> str:
    """Return the Claude model for the VLM document extractor.

    Deliberately decoupled from ``_configured_model``: the strict extraction
    contracts (``IntakeFact``/``LabFact`` — ``extra="forbid"``, every field a
    required key, flat-string values, non-empty ``source_citation``) demand a
    model capable of producing a schema-exact envelope, whereas the chat loop
    can run a faster/cheaper tier. So a deployment may set OE_AI_AGENT_MODEL to a
    fast tier (e.g. Haiku) for latency while extraction stays on the capable
    default — unless OE_AI_AGENT_EXTRACT_MODEL explicitly overrides it. Unset,
    extraction uses the historical Opus default regardless of the chat model.
    """
    return os.environ.get("OE_AI_AGENT_EXTRACT_MODEL") or _DEFAULT_MODEL


# The extractor fails over to these models, in order, when the primary extraction
# model returns a transient availability error (overloaded / rate-limited / 5xx).
# Sonnet is the default secondary: it satisfies the strict extraction contract
# (unlike a faster tier) and draws on separate capacity, so a busy Opus vision
# tier no longer fails an upload. Override/disable via OE_AI_AGENT_EXTRACT_FALLBACK_MODEL
# (comma-separated list; empty string disables fallover).
_DEFAULT_EXTRACT_FALLBACK = "claude-sonnet-4-6"


def _extract_fallback_models() -> tuple[str, ...]:
    """Return the ordered extraction fallback models, honoring the env override."""
    raw = os.environ.get("OE_AI_AGENT_EXTRACT_FALLBACK_MODEL")
    if raw is None:
        raw = _DEFAULT_EXTRACT_FALLBACK
    return tuple(m.strip() for m in raw.split(",") if m.strip())

_BEARER_PREFIX = "Bearer "


def _span(tracer: Any, metadata: dict[str, Any]) -> contextlib.AbstractContextManager[Any]:
    """Return the tracer's turn context manager, safely defaulting to a no-op.

    Observability must never break the request path: if there is no tracer, or
    ``tracer.turn(metadata)`` raises, a no-op context manager is returned so the
    agent still runs and the answer is still produced.
    """
    if tracer is None:
        return contextlib.nullcontext()
    try:
        return tracer.turn(metadata)
    except Exception:  # noqa: BLE001 - telemetry must never break the request
        logging.getLogger("sidecar").exception("tracer.turn failed; continuing without a span")
        return contextlib.nullcontext()


def _log_span_metrics(span: Any, summary: dict[str, Any] | None, *, success: bool, correlation_id: Any) -> None:
    """Attach per-turn dashboard metrics to the tracer span, fully guarded.

    Logs ``metrics``/``scores``/``metadata`` via ``span.log`` so a Braintrust
    dashboard can aggregate error rate, tool-call counts, retries, and the
    verification pass/fail rate. A log-less/None span, or a ``span.log`` error,
    is a silent no-op — telemetry must never break the request.
    """
    if span is None or not hasattr(span, "log"):
        return
    verdict = summary.get("verification_verdict") if summary else None
    scores = {"success": 1.0 if success else 0.0}
    if verdict is not None:
        scores["verification_pass"] = {"pass": 1.0, "pass_with_flags": 0.5, "blocked": 0.0}.get(verdict, 0.0)
    metrics = {k: summary[k] for k in ("tool_calls", "tool_failures", "model_calls",
               "input_tokens", "output_tokens", "cost_usd", "retries") if summary and k in summary}
    metadata = {"outcome": "ok" if success else "error", "verification_verdict": verdict,
                "truncated": bool(summary.get("truncated")) if summary else False,
                "degraded": bool(summary.get("degraded")) if summary else False,
                "correlation_id": correlation_id}
    try:
        span.log(metrics=metrics, scores=scores, metadata=metadata)
    except Exception:  # noqa: BLE001 - telemetry must never break the request
        logging.getLogger("sidecar").exception("span metric log failed; ignoring")


def _run_agent(
    agent: Any,
    question: str,
    pid: int,
    store: ConversationStore | None,
    conversation_id: Any,
    multi_turn: bool,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[str, list[Any] | None]:
    """Run one agent turn, returning ``(answer, new_history)``.

    ``new_history`` is the updated conversation history for the multi-turn path
    (so the caller can persist it), or ``None`` for the stateless path.

    When ``on_event`` is supplied (the streaming path) both the multi-turn and
    stateless branches go through ``run_turn`` so tool executions emit live
    status events either way — the stateless branch just starts from an empty
    history and discards the returned history. With ``on_event=None`` (the
    ``process_ask`` path) the stateless branch keeps using ``run`` byte-for-byte.
    """
    if multi_turn:
        assert store is not None  # multi_turn implies a store; narrows the type
        history = store.history(conversation_id, pid)
        if on_event is not None:
            answer, new_history = agent.run_turn(question, pid, history, on_event=on_event)
        else:
            answer, new_history = agent.run_turn(question, pid, history)
        return answer, new_history
    if on_event is not None:
        answer, _ = agent.run_turn(question, pid, None, on_event=on_event)
        return answer, None
    return agent.run(question, pid), None


# A parsed, valid request: (jwt, pid, question, conversation_id, multi_turn, metadata).
ParsedRequest = tuple[str, int, str, Any, bool, dict[str, Any]]


def _parse_request(
    authorization: str,
    raw_body: bytes,
    store: ConversationStore | None,
) -> tuple[int, dict[str, Any]] | ParsedRequest:
    """Validate a request's auth + body, shared by ``process_ask``/``stream_ask``.

    Returns a ``(status, {"error": ...})`` tuple on failure (matching
    ``process_ask``'s error contract), or the parsed request tuple on success.
    Callers distinguish the two by length: an error tuple has two elements.
    """
    if not authorization.startswith(_BEARER_PREFIX):
        return 401, {"error": "missing bearer token"}
    jwt = authorization[len(_BEARER_PREFIX):].strip()
    if jwt == "":
        return 401, {"error": "missing bearer token"}

    try:
        data = json.loads(raw_body or b"{}")
        pid = int(data.get("pid", 0))
        question = str(data.get("question", "")).strip()
        conversation_id = data.get("conversation_id")
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return 400, {"error": "invalid request"}

    if pid <= 0 or question == "":
        return 400, {"error": "pid and question are required"}

    multi_turn = store is not None and isinstance(conversation_id, str) and conversation_id != ""

    # Tag this turn's observability span with the patient (and, for multi-turn,
    # the conversation) so the auto-logged Claude calls group by conversation +
    # patient. Guarded end-to-end: a failing tracer never breaks the request.
    metadata: dict[str, Any] = {"pid": pid}
    if multi_turn:
        metadata["conversation_id"] = conversation_id

    return jwt, pid, question, conversation_id, multi_turn, metadata


def process_ask(
    authorization: str,
    raw_body: bytes,
    agent_builder: AgentBuilder,
    store: ConversationStore | None = None,
    tracer: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Validate a /ask request and run the agent. Returns (status, json_body).

    Pure and side-effect-free apart from the injected agent and (optional)
    conversation store: no sockets, so it is directly unit-testable. Never
    surfaces internal error detail to the caller.

    When ``store`` is supplied and the body carries a non-empty
    ``conversation_id``, the pid-scoped history is loaded, the turn continues it
    via ``run_turn``, and the updated history is persisted. Otherwise the request
    is stateless (``run``), keeping the 3-arg callers backward compatible.
    """
    parsed = _parse_request(authorization, raw_body, store)
    if len(parsed) == 2:
        status, body = parsed  # type: ignore[misc]
        return status, body
    jwt, pid, question, conversation_id, multi_turn, metadata = parsed  # type: ignore[misc]

    try:
        agent = agent_builder(pid, jwt)
        cid = getattr(agent, "correlation_id", None) or new_correlation_id()
        metadata["correlation_id"] = cid
        # Enter the span, but never let a span-lifecycle failure re-run the agent.
        # The agent is invoked from exactly ONE call site below so an agent error
        # (the expensive failure path) can never trigger a second LLM call.
        cm = _span(tracer, metadata)
        span = None
        try:
            span = cm.__enter__()
            entered = True
        except Exception:  # noqa: BLE001 - a span enter error must not break the request
            logging.getLogger("sidecar").exception("span __enter__ failed; continuing without it")
            entered = False

        try:
            result = _run_agent(agent, question, pid, store, conversation_id, multi_turn)
        except BaseException as e:
            # Agent error: log the error metrics, close the span (swallowing exit
            # errors), then let the exception propagate to the outer handler.
            if entered:
                _log_span_metrics(span, None, success=False, correlation_id=cid)
                try:
                    cm.__exit__(type(e), e, e.__traceback__)
                except Exception:  # noqa: BLE001 - a span exit error must not mask the real failure
                    logging.getLogger("sidecar").exception("span __exit__ failed; ignoring")
            raise
        else:
            if entered:
                # Attach per-turn dashboard metrics while the span is still open.
                observer = getattr(agent, "observer", None)
                summarize = getattr(observer, "summary", None)
                summary = summarize() if callable(summarize) else None
                _log_span_metrics(span, summary, success=True, correlation_id=cid)
                try:
                    cm.__exit__(None, None, None)
                except Exception:  # noqa: BLE001 - a span exit error must not break the request
                    logging.getLogger("sidecar").exception("span __exit__ failed; ignoring")

        answer, new_history = result
        if multi_turn and new_history is not None:
            store.remember(conversation_id, pid, new_history)
    except Exception:
        # Never leak internal detail (API errors, boundary failures) to the browser.
        cid = locals().get("cid") or new_correlation_id()
        logging.getLogger("sidecar").exception("agent turn failed cid=%s pid=%s", cid, pid)
        return 502, {"error": "the assistant is unavailable"}

    # Emit the turn's observability trace (tokens, cost, tool calls). Guarded so
    # non-instrumented agents (e.g. test fakes) don't error. The cid is always in
    # the message so a full trace can be reconstructed from the log alone.
    observer = getattr(agent, "observer", None)
    summarize = getattr(observer, "summary", None)
    trace = json.dumps(summarize()) if callable(summarize) else "null"
    logging.getLogger("sidecar").info("agent turn: cid=%s pid=%s trace=%s", cid, pid, trace)

    return 200, {"answer": answer, "correlation_id": cid}


def _sse_frame(name: str, data: dict[str, Any]) -> bytes:
    """Format a single Server-Sent Events frame as utf-8 bytes."""
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def stream_ask(
    authorization: str,
    raw_body: bytes,
    agent_builder: AgentBuilder,
    store: ConversationStore | None = None,
    tracer: Any = None,
) -> Iterator[bytes]:
    """Validate a /ask/stream request and yield SSE frames for the turn.

    Pure and socket-free (the caller adapts it to the HTTP response). Reuses the
    exact validation of ``process_ask`` via ``_parse_request``. Status/tool
    events stream live during the turn; the answer text is buffered, run through
    the verification gate (inside ``run_turn``), and only the gated answer is
    emitted — so no unverified clinical content ever reaches the client. Never
    surfaces internal error detail.
    """
    parsed = _parse_request(authorization, raw_body, store)
    if len(parsed) == 2:
        status, body = parsed  # type: ignore[misc]
        yield _sse_frame("error", {"status": status, "error": body["error"]})
        return
    jwt, pid, question, conversation_id, multi_turn, metadata = parsed  # type: ignore[misc]

    yield _sse_frame("status", {"stage": "start"})

    # Threaded producer/consumer bridge: the agent turn runs on a worker thread
    # and pushes each tool event onto ``q`` the instant it fires (via on_event),
    # so this generator can yield the corresponding ``tool`` frame live — while
    # the model calls and the verification gate are still blocking. The answer
    # text stays buffered inside run_turn, is gated once on the complete draft,
    # and is emitted last in a single ``answer`` frame; no answer text ever flows
    # through on_event. A ``("done", None)`` sentinel signals the worker finished,
    # so every real tool event is yielded before the answer frame.
    q: queue.Queue[tuple[str, Any]] = queue.Queue()
    on_event = lambda ev: q.put(("event", ev))  # noqa: E731
    result: dict[str, Any] = {}

    def _worker() -> None:
        # The span is entered INSIDE the worker, after the agent is built, so the
        # per-invocation correlation id can be tagged onto the span metadata (the
        # id is only known post-build). The span wraps the single agent call; a
        # span-lifecycle failure must never re-run the agent or break the stream.
        cm = None
        entered = False
        try:
            # Build the agent inside the guarded worker so a builder failure is
            # masked to an ``error`` frame too (parity with process_ask), rather
            # than raising on the HTTP thread after the status frame is flushed.
            agent = agent_builder(pid, jwt)
            result["agent"] = agent  # for the post-run observability trace
            cid = getattr(agent, "correlation_id", None) or new_correlation_id()
            result["cid"] = cid
            # Tag the span metadata with the cid, then open the span around the run
            # so the observability trace is joinable to the cid (parity w/ process_ask).
            metadata["correlation_id"] = cid
            cm = _span(tracer, metadata)
            span = None
            try:
                span = cm.__enter__()
                entered = True
            except Exception:  # noqa: BLE001 - a span enter error must not break the request
                logging.getLogger("sidecar").exception("span __enter__ failed; continuing without it")
                entered = False
            result["span"] = span
            answer, new_history = _run_agent(
                agent, question, pid, store, conversation_id, multi_turn, on_event=on_event
            )
            result["answer"] = answer
            result["history"] = new_history
            # Attach per-turn dashboard metrics while the span is still open (the
            # finally below exits it). Guarded so telemetry never breaks the stream.
            if entered:
                observer = getattr(agent, "observer", None)
                summarize = getattr(observer, "summary", None)
                summary = summarize() if callable(summarize) else None
                _log_span_metrics(span, summary, success=True, correlation_id=cid)
        except BaseException as e:  # noqa: BLE001 - capture; never crash the worker thread
            result["error"] = e
            if entered:
                _log_span_metrics(result.get("span"), None, success=False, correlation_id=result.get("cid"))
        finally:
            if entered and cm is not None:
                exc = result.get("error")
                try:
                    if exc is not None:
                        cm.__exit__(type(exc), exc, exc.__traceback__)
                    else:
                        cm.__exit__(None, None, None)
                except Exception:  # noqa: BLE001 - a span exit error must not mask/break anything
                    logging.getLogger("sidecar").exception("span __exit__ failed; ignoring")
            q.put(("done", None))

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    # Drain the queue, yielding tool frames live until the worker's sentinel.
    while True:
        kind, payload = q.get()
        if kind == "done":
            break
        yield _sse_frame("tool", payload)

    worker.join()

    # Resolve the cid for logging; fall back to a fresh one if the worker failed
    # before building the agent, so logging never crashes.
    cid = result.get("cid") or new_correlation_id()

    if result.get("error") is not None:
        # Never leak internal detail (API errors, boundary failures) to the browser.
        logging.getLogger("sidecar").exception(
            "agent turn failed cid=%s pid=%s", cid, pid, exc_info=result["error"]
        )
        yield _sse_frame("error", {"error": "the assistant is unavailable"})
        return

    answer = result["answer"]
    new_history = result.get("history")
    if multi_turn and new_history is not None:
        assert store is not None
        store.remember(conversation_id, pid, new_history)

    # Emit the turn's observability trace (tokens, cost, tool calls). Guarded so
    # non-instrumented agents (e.g. test fakes) don't error. The cid is always in
    # the message so a full trace can be reconstructed from the log alone.
    observer = getattr(result.get("agent"), "observer", None)
    summarize = getattr(observer, "summary", None)
    trace = json.dumps(summarize()) if callable(summarize) else "null"
    logging.getLogger("sidecar").info("agent turn: cid=%s pid=%s trace=%s", cid, pid, trace)

    yield _sse_frame("answer", {"answer": answer})
    yield _sse_frame("done", {"ok": True, "correlation_id": cid})


def default_agent_builder(
    summary_url: str,
    message_creator: Any,
    read_url: str | None = None,
) -> AgentBuilder:
    """Build a per-request ClaudeAgent bound to the forwarded JWT.

    The agent gets the built-in summary tool plus the operation-dispatched chart
    tools (list_encounters / get_encounter) that POST to read.php with the same
    forwarded JWT, the ``get_intake_form`` tool that reads the patient's intake
    form through the same boundary and returns its extracted, citable facts, plus
    the ``evidence_retriever`` guideline-evidence tool that runs hybrid retrieval
    over the shared, build-once guideline index. ``read_url`` defaults to the
    summary URL with ``summary.php`` swapped for ``read.php``.
    """
    chart_url = read_url or summary_url.replace("summary.php", "read.php")
    # Per-turn tool-execution budget; overridable via env (defaults to 8).
    max_tool_calls = int(os.environ.get("OE_AI_AGENT_MAX_TOOL_CALLS") or "8")
    model = _configured_model()
    # The intake tool runs the VLM extractor mid-turn, so it uses the capable
    # extraction model (see _extract_model) rather than the chat-loop model —
    # a fast chat tier must not weaken the strict-contract extraction. It fails
    # over to the extraction fallback models when the primary is overloaded.
    extract_model = _extract_model()
    extract_fallbacks = _extract_fallback_models()

    def build(pid: int, jwt: str) -> ClaudeAgent:
        cid = new_correlation_id()
        boundary = build_boundary(summary_url, jwt, correlation_id=cid)
        chart_boundary = build_chart_boundary(chart_url, jwt, correlation_id=cid)
        observer = TraceCollector()
        return ClaudeAgent(
            message_creator,
            boundary,
            model=model,
            observer=observer,
            extra_tools=build_encounter_tools(chart_boundary)
            + [
                build_results_tool(chart_boundary),
                build_medications_tool(chart_boundary),
                build_search_tool(chart_boundary),
            ]
            + build_documents_tools(chart_boundary)
            + [
                build_intake_tool(chart_boundary, message_creator, extract_model, extract_fallbacks),
                build_evidence_retriever_tool(
                    get_guideline_index(), tracer=observer
                ),
            ],
            max_tool_calls=max_tool_calls,
            correlation_id=cid,
        )

    return build


# A parsed, valid extract request: (jwt, pid, document_id, doc_type).
ParsedExtractRequest = tuple[str, int, int, str]


def _parse_extract_request(
    authorization: str,
    raw_body: bytes,
) -> tuple[int, dict[str, Any]] | ParsedExtractRequest:
    """Validate an /extract request's auth + body.

    Returns a ``(status, {"error": ...})`` tuple on failure, or the parsed
    request tuple on success. Callers distinguish the two by length: an error
    tuple has two elements. The pid is taken from the body (like /ask) and the
    boundary re-checks the JWT scope on the ``get_document`` read, so a token
    minted for another patient is rejected at the boundary, not trusted here.
    """
    if not authorization.startswith(_BEARER_PREFIX):
        return 401, {"error": "missing bearer token"}
    jwt = authorization[len(_BEARER_PREFIX):].strip()
    if jwt == "":
        return 401, {"error": "missing bearer token"}

    try:
        data = json.loads(raw_body or b"{}")
        pid = int(data.get("pid", 0))
        document_id = int(data.get("document_id", 0))
        doc_type = str(data.get("doc_type", "")).strip()
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return 400, {"error": "invalid request"}

    if pid <= 0 or document_id <= 0 or doc_type not in _DOC_TYPES:
        return 400, {"error": "pid, document_id and a valid doc_type are required"}

    return jwt, pid, document_id, doc_type


def process_extract(
    authorization: str,
    raw_body: bytes,
    extract_fn: ExtractFn,
) -> tuple[int, dict[str, Any]]:
    """Validate an /extract request and run the VLM extractor. Returns (status, body).

    Pure apart from the injected ``extract_fn`` (no sockets), so it is directly
    unit-testable. On success returns the strict, validated fact envelope; never
    surfaces internal error detail to the caller. A schema-invalid extraction
    (the VLM omitted a required field or invented an extra one — the contract's
    own guarantee) is reported as a 422 the card can show as "couldn't extract",
    distinct from a 502 for an unavailable extractor/boundary/VLM.
    """
    parsed = _parse_extract_request(authorization, raw_body)
    if len(parsed) == 2:
        status, body = parsed  # type: ignore[misc]
        return status, body
    jwt, pid, document_id, doc_type = parsed  # type: ignore[misc]

    try:
        body = extract_fn(pid, jwt, document_id, doc_type)
    except (ValidationError, ValueError, KeyError) as e:
        # The extraction ran but did not yield a contract-valid fact (missing/
        # hallucinated field, malformed VLM envelope). Not an outage — tell the
        # caller it couldn't be extracted, without leaking which field or why.
        logging.getLogger("sidecar").warning(
            "extract produced no valid fact pid=%s doc=%s: %s", pid, document_id, type(e).__name__
        )
        return 422, {"error": "could not extract a valid fact from this document"}
    except Exception:  # noqa: BLE001 - never leak boundary/API detail to the browser
        logging.getLogger("sidecar").exception(
            "extract failed pid=%s doc=%s", pid, document_id
        )
        return 502, {"error": "document extraction is unavailable"}

    return 200, body


def default_extract_builder(
    summary_url: str,
    message_creator: Any,
    read_url: str | None = None,
    word_geometry: Any = None,
) -> ExtractFn:
    """Build the extract-fn: fetch the stored document pid-scoped and extract it.

    Mirrors ``default_agent_builder``'s wiring — a per-request ``chart_boundary``
    bound to the forwarded JWT (so the ``get_document`` read re-checks the token
    scope at read.php) plus the shared VLM ``message_creator``. Returns the
    validated ``LabFact``/``IntakeFact`` as a JSON-safe envelope.
    """
    chart_url = read_url or summary_url.replace("summary.php", "read.php")
    model = _extract_model()
    fallback_models = _extract_fallback_models()

    def extract(pid: int, jwt: str, document_id: int, doc_type: str) -> dict[str, Any]:
        cid = new_correlation_id()
        chart_boundary = build_chart_boundary(chart_url, jwt, correlation_id=cid)
        log_event(INGESTION_START, cid, document_id=document_id, doc_type=doc_type)
        result = attach_and_extract(
            pid,
            document_id,
            doc_type,
            chart_boundary=chart_boundary,
            message_creator=message_creator,
            model=model,
            fallback_models=fallback_models,
        )
        # Only the validated fact + PHI-free telemetry cross back to the browser;
        # never the raw document bytes or the VLM's unparsed text.
        body: dict[str, Any] = {
            "ok": True,
            "doc_type": result.doc_type,
            "confidence": result.confidence,
            "low_confidence": result.low_confidence,
            "unsupported_fields": result.unsupported_fields,
            "fact": result.fact.model_dump(),
            "correlation_id": cid,
        }
        log_event(INGESTION_COMPLETE, cid, document_id=document_id, doc_type=doc_type)

        # Proactive, deterministic wrong-chart / wrong-patient check at
        # extraction time (intake forms only). Best-effort and fail-open: any
        # error fetching the chart demographics or running the check simply
        # omits `identity_check` — a verification outage must never block the
        # extracted fact, and we never cry wolf on an unverifiable upload.
        if doc_type == "intake_form":
            try:
                summary = build_boundary(summary_url, jwt, correlation_id=cid)(pid)
                demographics = summary.get("demographics")
                check = check_identity(result.fact.demographics, demographics)
                body["identity_check"] = {
                    "matches": check.matches,
                    "mismatched_identifiers": check.mismatched_identifiers,
                    "warning": None if check.matches else "possible_wrong_chart",
                }
            except Exception:  # noqa: BLE001 - fail-open on any verification error
                logging.getLogger("sidecar").warning(
                    "identity check skipped pid=%s doc=%s", pid, document_id
                )

        # Optional citation overlay: when a word-geometry provider is wired,
        # locate the fact's source citation on the page and carry the covering
        # box(es) + page dimensions back for the card to draw.
        if word_geometry is not None:
            geom = word_geometry(pid, document_id, doc_type)
            if geom:
                body["citation_boxes"] = locate_citation_boxes(
                    geom["words"], result.fact.source_citation
                )
                body["page_width"] = geom["page_width"]
                body["page_height"] = geom["page_height"]

        return body

    return extract


def make_handler(
    agent_builder: AgentBuilder,
    allow_origin: str,
    store: ConversationStore | None = None,
    tracer: Any = None,
    extract_fn: ExtractFn | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a request-handler class bound to an agent-builder and CORS origin.

    An optional ``ConversationStore`` enables multi-turn context for requests
    that carry a ``conversation_id``. An optional ``extract_fn`` enables the
    ``POST /extract`` document-extraction endpoint (auto-extract on upload); when
    it is ``None`` that route replies 404 like any other unknown path.
    """

    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if "correlation_id" in body:
                self.send_header("X-Correlation-ID", str(body["correlation_id"]))
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self) -> None:  # noqa: N802 (http.server naming)
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            path = self.path.rstrip("/") or "/"
            if path == "/health":
                self._send_json(200, liveness())          # liveness: unconditional 200
                return
            if path == "/ready":
                summary_url = os.environ.get(
                    "OE_AI_AGENT_SUMMARY_URL",
                    "http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php",
                )
                status, body = ready_response(
                    summary_url,
                    os.environ.get("ANTHROPIC_API_KEY"),
                    os.environ.get("BRAINTRUST_API_KEY"),
                    urllib.request.urlopen,
                )
                self._send_json(status, body)
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 (http.server naming)
            path = self.path.rstrip("/")
            extract_enabled = extract_fn is not None
            valid_paths = ("/ask", "/ask/stream")
            if extract_enabled:
                valid_paths = valid_paths + ("/extract",)
            if path not in valid_paths:
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b""
            authorization = self.headers.get("Authorization", "")

            if path == "/extract":
                assert extract_fn is not None  # narrowed by valid_paths above
                status, body = process_extract(authorization, raw_body, extract_fn)
                self._send_json(status, body)
                return

            if path == "/ask/stream":
                # This streamed response has no Content-Length and is not chunked,
                # so end-of-body is signalled by closing the connection. Declare
                # ``Connection: close`` (and force the server to actually close)
                # so the browser reads a clean EOF and the fetch stream resolves;
                # a lingering ``keep-alive`` here makes strict clients treat the
                # socket close as a truncated/errored response.
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self._cors()
                self.end_headers()
                try:
                    for frame in stream_ask(authorization, raw_body, agent_builder, store, tracer):
                        self.wfile.write(frame)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    # The client went away mid-stream (closed the tab / navigated).
                    # Nothing left to deliver; stop quietly rather than 500-ing.
                    pass
                return

            status, body = process_ask(
                authorization,
                raw_body,
                agent_builder,
                store,
                tracer,
            )
            self._send_json(status, body)

        def log_message(self, *args: Any) -> None:  # keep the console quiet
            pass

    return Handler


def load_env_file(path: str) -> None:
    """Load simple KEY=VALUE lines from a .env file into os.environ.

    Best-effort and dependency-free: blank lines and '#' comments are skipped,
    surrounding quotes are stripped, and existing environment variables are not
    overwritten (an explicit export always wins over the file).
    """
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line == "" or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_env_file(os.path.join(os.path.dirname(__file__), ".env"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is required to run the sidecar.")

    summary_url = os.environ.get(
        "OE_AI_AGENT_SUMMARY_URL",
        "http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php",
    )
    read_url = os.environ.get("OE_AI_AGENT_READ_URL") or summary_url.replace("summary.php", "read.php")
    allow_origin = os.environ.get("OE_AI_AGENT_ALLOW_ORIGIN", "*")
    # On a platform that assigns a port (Railway sets $PORT), bind all interfaces
    # on that port by default; locally, stay on loopback:8900.
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"  # nosec B104 # bind-all only when a platform ($PORT) requires it; loopback otherwise
    host = os.environ.get("OE_AI_AGENT_HOST", default_host)
    port = int(os.environ.get("OE_AI_AGENT_PORT") or os.environ.get("PORT") or "8900")

    message_creator = build_message_creator(api_key)
    # Ephemeral, pid-scoped, TTL-bounded store so follow-up questions carry
    # context across turns (in-memory only — no PHI persisted to disk).
    store = ConversationStore()
    # Optional Braintrust turn-tracer: no-op unless BRAINTRUST_API_KEY is set,
    # and fully guarded so observability can never break the request path.
    tracer = build_tracer()
    handler = make_handler(
        default_agent_builder(summary_url, message_creator, read_url),
        allow_origin,
        store,
        tracer,
        default_extract_builder(summary_url, message_creator, read_url),
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"AI sidecar listening on http://{host}:{port}/ask -> {summary_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
