"""T11 acceptance tests (LOCKED) for the sidecar observability spine.

The agent records per-model-response token usage (→ cost) and per-tool success/failure,
and recovers from a boundary failure instead of crashing. Unit tests with injected fakes.
"""
from types import SimpleNamespace

from agent import ClaudeAgent
from observability import NullObserver, TraceCollector


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name="get_patient_summary", id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input={}, id=id)


def _usage(i, o):
    return SimpleNamespace(input_tokens=i, output_tokens=o)


def _resp(blocks, stop_reason, usage=None):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage)


class ScriptedCreator:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class Boundary:
    def __init__(self, summary=None, raises=False):
        self.summary = summary or {}
        self.raises = raises

    def __call__(self, pid):
        if self.raises:
            raise RuntimeError("boundary unavailable")
        return self.summary


def _error_results(messages):
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("is_error"):
                    out.append(b)
    return out


def test_trace_records_tokens_tools_and_cost():
    creator = ScriptedCreator([
        _resp([_tool_use()], "tool_use", usage=_usage(100, 50)),
        _resp([_text("The patient is stable.")], "end_turn", usage=_usage(100, 50)),
    ])
    trace = TraceCollector(model="claude-opus-4-8")
    agent = ClaudeAgent(creator, Boundary({"demographics": {}}), observer=trace)

    agent.run("How is the patient?", pid=42)

    s = trace.summary()
    assert s["model_calls"] == 2
    assert s["input_tokens"] == 200
    assert s["output_tokens"] == 100
    assert s["tool_calls"] == 1
    assert s["tool_failures"] == 0
    # 200/1e6 * $5  +  100/1e6 * $25  =  0.001 + 0.0025 = 0.0035
    assert abs(s["cost_usd"] - 0.0035) < 1e-9


def test_boundary_failure_is_recorded_and_agent_recovers():
    creator = ScriptedCreator([
        _resp([_tool_use()], "tool_use", usage=_usage(10, 10)),
        _resp([_text("I could not retrieve the chart.")], "end_turn", usage=_usage(10, 10)),
    ])
    trace = TraceCollector(model="claude-opus-4-8")
    agent = ClaudeAgent(creator, Boundary(raises=True), observer=trace)

    result = agent.run("summarize", pid=42)  # must NOT raise

    # startswith, not equality: T31 appends a partial-failure disclosure on the
    # failed-tool path (this is that path). The clinical text is intact.
    assert result.startswith("I could not retrieve the chart.")
    assert "may be incomplete" in result.lower()   # the failure is surfaced, not silent
    s = trace.summary()
    assert s["tool_calls"] == 1
    assert s["tool_failures"] == 1
    # an is_error tool_result was fed back to the model
    assert len(_error_results(creator.calls[1]["messages"])) == 1


def test_null_observer_is_the_default():
    creator = ScriptedCreator([_resp([_text("hi")], "end_turn")])
    # no observer arg → NullObserver; no usage on the response; must not crash
    assert ClaudeAgent(creator, Boundary({})).run("q", pid=1) == "hi"


def test_response_without_usage_counts_as_a_call_but_costs_zero():
    creator = ScriptedCreator([_resp([_text("hi")], "end_turn", usage=None)])
    trace = TraceCollector(model="claude-opus-4-8")
    ClaudeAgent(creator, Boundary({}), observer=trace).run("q", pid=1)

    s = trace.summary()
    assert s["model_calls"] == 1
    assert s["input_tokens"] == 0
    assert s["cost_usd"] == 0.0


def test_null_observer_methods_are_noops():
    obs = NullObserver()
    obs.record_model_response(10, 20)
    obs.record_tool_call("x", True)  # should not raise or track anything
