"""T31 acceptance tests (LOCKED) — partial-failure disclosure.

Failure Modes: the agent degrades gracefully when a tool fails (catches it, feeds
an is_error result back, keeps going), but that partial failure must be
COMMUNICATED, not silent — else a degraded answer presents as authoritative. When
any tool returned is_error during the turn, the answer carries a "may be
incomplete" disclosure (appended after the verification gate) and a
`{"type": "degraded", "reason": "tool_failure"}` event is emitted. A fully-
successful turn is unchanged. Parallels the T30 truncation disclosure and composes
with it. Deterministic; no anthropic SDK, no sockets, no live API call.
"""
from types import SimpleNamespace

from agent import ClaudeAgent


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ScriptedCreator:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class RecordingBoundary:
    def __init__(self, summary):
        self.summary = summary

    def __call__(self, pid):
        return self.summary


class BoomBoundary:
    def __call__(self, pid):
        raise RuntimeError("boundary down")


def _boom(pid, inp):
    raise RuntimeError("tool down")


def _spec(name, handler):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


# --- a failed tool -> disclosure + degraded event ------------------------------

def test_failing_handler_marks_answer_incomplete_and_emits_degraded_event():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("Here is what I could gather.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("get_medications", _boom)])

    events = []
    answer, _ = agent.run_turn("what meds?", pid=42, on_event=events.append)

    assert "may be incomplete" in answer.lower()
    assert any(e.get("type") == "degraded" and e.get("reason") == "tool_failure" for e in events)
    assert sum(1 for e in events if e.get("type") == "degraded") == 1


def test_boundary_failure_marks_answer_incomplete():
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {}, "t1")], "tool_use"),
        _resp([_text("Partial view only.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, BoomBoundary())

    answer = agent.run("summarize", pid=42)
    assert "may be incomplete" in answer.lower()


def test_unknown_tool_marks_answer_incomplete():
    creator = ScriptedCreator([
        _resp([_tool_use("no_such_tool", {}, "t1")], "tool_use"),
        _resp([_text("Answered without it.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}))

    events = []
    answer, _ = agent.run_turn("do something", pid=42, on_event=events.append)
    assert "may be incomplete" in answer.lower()
    assert any(e.get("type") == "degraded" for e in events)


def test_clinical_text_preserved_alongside_the_notice():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("The patient is on Warfarin.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("get_medications", _boom)])

    answer = agent.run("what meds?", pid=42)
    assert "The patient is on Warfarin." in answer
    assert "may be incomplete" in answer.lower()


# --- a fully-successful turn is unchanged --------------------------------------

def test_all_tools_succeed_is_not_marked_incomplete():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("The patient is on Warfarin.")], "end_turn"),
    ])
    ok = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[ok])

    events = []
    answer, _ = agent.run_turn("what meds?", pid=42, on_event=events.append)
    assert "may be incomplete" not in answer.lower()
    assert not any(e.get("type") == "degraded" for e in events)


def test_immediate_answer_no_tools_is_not_marked_incomplete():
    creator = ScriptedCreator([_resp([_text("The patient is stable.")], "end_turn")])
    agent = ClaudeAgent(creator, RecordingBoundary({}))
    assert "may be incomplete" not in agent.run("how is the patient?", pid=42).lower()


# --- backward compatibility + composition with T30 -----------------------------

def test_failed_tool_without_on_event_appends_notice_and_does_not_crash():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("Best effort.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("get_medications", _boom)])
    assert "may be incomplete" in agent.run("what meds?", pid=42).lower()   # on_event=None


def test_degraded_under_budget_is_not_also_truncated():
    # One failed tool, default budget (8) -> degraded but NOT truncated.
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("Best effort.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("get_medications", _boom)])

    events = []
    answer, _ = agent.run_turn("what meds?", pid=42, on_event=events.append)
    assert any(e.get("type") == "degraded" for e in events)
    assert not any(e.get("type") == "truncated" for e in events)
    assert "lookup limit" not in answer.lower()
