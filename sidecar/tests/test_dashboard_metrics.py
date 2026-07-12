"""T38 acceptance tests (LOCKED) — per-turn dashboard metrics on the Braintrust span.

The observability collector captures the verification verdict and the
truncated/degraded/retry signals; process_ask and stream_ask attach the full
per-turn metric set to the tracer span via span.log(metrics=, scores=, metadata=)
so a Braintrust dashboard can aggregate error rate, tool-call counts, retries, and
verification pass/fail rate. Guarded: a log-less span never breaks the request.
Deterministic — scripted SDK fakes, no live API, no braintrust import.
"""
import json
import os
from types import SimpleNamespace

from agent import ClaudeAgent
from observability import NullObserver, TraceCollector
from server import process_ask, stream_ask


# --- scripted fakes ------------------------------------------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ScriptedCreator:
    def __init__(self, responses):
        self._responses = list(responses)

    def __call__(self, **kwargs):
        return self._responses.pop(0)


def _spec(name, handler):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


_GATED_PASS = (
    "The patient is stable [S1].\n```citations\n"
    + json.dumps([{"n": 1, "ref": "openemr:_absence"}])
    + "\n```"
)
_GATED_BLOCKED = (
    "See MRN 998877 [S1].\n```citations\n"
    + json.dumps([{"n": 1, "ref": "openemr:_absence"}])
    + "\n```"
)


class RecordingSpan:
    def __init__(self):
        self.logged = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def log(self, **kwargs):
        self.logged.append(kwargs)


class RecordingTracer:
    def __init__(self):
        self.spans = []

    def turn(self, metadata):
        s = RecordingSpan()
        self.spans.append(s)
        return s


def _body(pid=42, q="hi"):
    return json.dumps({"pid": pid, "question": q}).encode("utf-8")


# --- collector: new signals ----------------------------------------------------

def test_collector_defaults_for_new_fields():
    s = TraceCollector().summary()
    assert s["verification_verdict"] is None
    assert s["truncated"] is False
    assert s["degraded"] is False
    assert s["retries"] == 0


def test_collector_records_verdict_truncated_degraded_retry():
    c = TraceCollector()
    c.record_verification("blocked")
    c.record_truncated()
    c.record_degraded()
    c.record_retry()
    c.record_retry()
    s = c.summary()
    assert s["verification_verdict"] == "blocked"
    assert s["truncated"] is True
    assert s["degraded"] is True
    assert s["retries"] == 2


def test_null_observer_has_new_noops():
    n = NullObserver()
    n.record_verification("pass")
    n.record_truncated()
    n.record_degraded()
    n.record_retry()  # must not raise


# --- the gate verdict is recorded through a run --------------------------------

def test_run_records_a_pass_verdict_on_the_observer():
    agent = ClaudeAgent(ScriptedCreator([_resp([_text(_GATED_PASS)], "end_turn")]),
                        lambda pid: {}, observer=TraceCollector())
    agent.run("how is the patient?", pid=42)
    assert agent.observer.summary()["verification_verdict"] == "pass"


def test_run_records_a_blocked_verdict_on_the_observer():
    agent = ClaudeAgent(ScriptedCreator([_resp([_text(_GATED_BLOCKED)], "end_turn")]),
                        lambda pid: {}, observer=TraceCollector())
    agent.run("look it up", pid=42)
    assert agent.observer.summary()["verification_verdict"] == "blocked"


# --- run_turn records truncated / degraded -------------------------------------

def test_run_records_truncated_when_budget_spent():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("Best effort.")], "end_turn"),
    ])
    meds = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1"}])
    agent = ClaudeAgent(creator, lambda pid: {}, extra_tools=[meds],
                        observer=TraceCollector(), max_tool_calls=1)
    agent.run("meds?", pid=42)
    assert agent.observer.summary()["truncated"] is True


def test_run_records_degraded_on_tool_failure():
    def boom(pid, inp):
        raise RuntimeError("down")
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("Best effort.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, lambda pid: {}, extra_tools=[_spec("get_medications", boom)],
                        observer=TraceCollector())
    agent.run("meds?", pid=42)
    assert agent.observer.summary()["degraded"] is True


# --- process_ask / stream_ask attach metrics to the span ----------------------

def _pass_builder():
    def builder(pid, jwt):
        creator = ScriptedCreator([
            _resp([_tool_use("get_patient_summary", {}, "t1")], "tool_use"),
            _resp([_text(_GATED_PASS)], "end_turn"),
        ])
        return ClaudeAgent(creator, lambda p: {}, observer=TraceCollector())
    return builder


def _find_metric_log(span):
    # the per-turn metric log carries a 'metrics' or 'scores' payload
    return next((e for e in span.logged if "metrics" in e or "scores" in e), None)


def test_process_ask_logs_metrics_scores_and_metadata_to_span():
    tracer = RecordingTracer()
    status, body = process_ask("Bearer jwt", _body(), _pass_builder(), tracer=tracer)
    assert status == 200
    entry = _find_metric_log(tracer.spans[0])
    assert entry is not None
    assert entry["metrics"]["tool_calls"] == 1
    assert entry["scores"]["success"] == 1.0
    assert entry["scores"]["verification_pass"] == 1.0
    assert entry["metadata"]["verification_verdict"] == "pass"


def test_stream_ask_logs_metrics_to_span():
    tracer = RecordingTracer()
    b"".join(stream_ask("Bearer jwt", _body(), _pass_builder(), tracer=tracer))
    entry = _find_metric_log(tracer.spans[0])
    assert entry is not None
    assert entry["metrics"]["tool_calls"] == 1
    assert entry["scores"]["success"] == 1.0


def test_logless_span_never_breaks_the_request():
    # Default tracer (NullTracer via None) yields a log-less/None span -> no crash.
    status, body = process_ask("Bearer jwt", _body(), _pass_builder())
    assert status == 200
    assert body["answer"]


# --- dashboard spec documents the required metrics -----------------------------

def test_dashboard_doc_names_the_required_metrics():
    path = os.path.join(os.path.dirname(__file__), "..", "DASHBOARD.md")
    with open(path) as fh:
        text = fh.read().lower()
    for term in ("request", "error rate", "latency", "tool call", "retry", "verification"):
        assert term in text, f"DASHBOARD.md missing: {term}"
