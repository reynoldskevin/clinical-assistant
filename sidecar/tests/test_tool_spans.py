"""T82 acceptance tests (LOCKED) — per-tool Braintrust spans.

The Braintrust monitor's built-in Tool executions / error rate / duration charts
aggregate spans of `type="tool"`. The agent never emitted those (it only counted
tool calls in-process), so the charts were empty. These tests pin that the agent
opens ONE tool span per tool execution, that a failure propagates through the
span (so Braintrust marks it errored), that a broken tracer never breaks the
turn, and that the Braintrust tracer tags the span `type="tool"`.

Deterministic/offline: scripted model, fake boundary/tracer, a fake `braintrust`
module injected for the type-contract test. No SDK, no network, no key.
"""
import contextlib
import sys
from types import SimpleNamespace

from agent import ClaudeAgent


# --- scripted model + boundary fakes ------------------------------------------

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


class Boundary:
    def __init__(self, summary=None, fail=False):
        self._summary = summary or {}
        self._fail = fail

    def __call__(self, pid):
        if self._fail:
            raise RuntimeError("boundary down")
        return self._summary


def _spec(name, handler):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


# --- fake tracer that records tool_span usage ---------------------------------

class RecordingSpan:
    def __init__(self, name):
        self.name = name
        self.error = None
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.error = exc_type
        return False  # never suppress — the agent handles the error itself


class RecordingTracer:
    def __init__(self):
        self.spans = []

    def turn(self, metadata):
        return contextlib.nullcontext()

    def tool_span(self, name):
        span = RecordingSpan(name)
        self.spans.append(span)
        return span


class BrokenTracer:
    def turn(self, metadata):
        return contextlib.nullcontext()

    def tool_span(self, name):
        raise RuntimeError("tracer boom")


# --- AC2: one tool span per tool execution ------------------------------------

def test_agent_opens_a_tool_span_per_tool_execution():
    tracer = RecordingTracer()
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {}, "t1")], "tool_use"),
        _resp([_tool_use("get_medications", {}, "t2")], "tool_use"),
        _resp([_text("done")], "end_turn"),
    ])
    med = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])
    agent = ClaudeAgent(creator, Boundary({"problems": []}), extra_tools=[med], tracer=tracer)

    agent.run("what meds?", pid=42)

    names = [s.name for s in tracer.spans]
    assert names == ["get_patient_summary", "get_medications"]
    assert all(s.entered for s in tracer.spans)


# --- AC3: a failing tool propagates through its span; the turn survives --------

def test_a_failing_injected_tool_marks_its_span_and_the_turn_recovers():
    tracer = RecordingTracer()
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("recovered")], "end_turn"),
    ])

    def boom(pid, inp):
        raise RuntimeError("tool failed")

    agent = ClaudeAgent(creator, Boundary({}), extra_tools=[_spec("get_medications", boom)], tracer=tracer)
    answer = agent.run("what meds?", pid=42)

    assert "recovered" in answer  # the loop fed the error back and continued
    span = next(s for s in tracer.spans if s.name == "get_medications")
    assert span.error is not None  # the exception passed THROUGH the tool span


def test_a_failing_summary_read_marks_its_span():
    tracer = RecordingTracer()
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {}, "t1")], "tool_use"),
        _resp([_text("ok")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, Boundary(fail=True), tracer=tracer)

    agent.run("summary?", pid=42)

    span = next(s for s in tracer.spans if s.name == "get_patient_summary")
    assert span.error is not None


# --- AC4: a broken tracer never breaks the turn -------------------------------

def test_a_broken_tracer_never_breaks_the_turn():
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {}, "t1")], "tool_use"),
        _resp([_text("still answered")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, Boundary({}), tracer=BrokenTracer())

    answer = agent.run("summary?", pid=42)
    assert "still answered" in answer


# --- AC1: the Braintrust tracer tags the span type="tool" ---------------------

def test_braintrust_tracer_opens_a_typed_tool_span(monkeypatch):
    calls = []

    def _start_span(**kwargs):
        calls.append(kwargs)
        return contextlib.nullcontext()

    fake_bt = SimpleNamespace(init_logger=lambda **k: None, start_span=_start_span)
    monkeypatch.setitem(sys.modules, "braintrust", fake_bt)
    monkeypatch.setenv("BRAINTRUST_API_KEY", "test-key")

    from factory import build_tracer
    tracer = build_tracer()
    with tracer.tool_span("get_medications"):
        pass

    assert any(c.get("type") == "tool" and c.get("name") == "get_medications" for c in calls), calls


def test_null_tracer_tool_span_is_a_noop(monkeypatch):
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    from factory import build_tracer
    tracer = build_tracer()  # NullTracer without a key
    with tracer.tool_span("x"):
        pass  # no error, no span
