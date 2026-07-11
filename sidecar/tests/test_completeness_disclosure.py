"""T30 acceptance tests (LOCKED) — completeness-boundary disclosure.

Speed vs. Completeness: the agent bounds work at max_tool_calls; once spent it is
forced to answer on partial data. That deferral must be COMMUNICATED, not silent.
When the budget is exhausted the answer carries a "lookup limit" disclosure
(appended after the verification gate, so grounding is untouched) and a
`{"type": "truncated", "reason": "tool_budget"}` event is emitted on the status
channel. A natural under-budget answer is unchanged. Deterministic; no anthropic
SDK, no sockets, no live API call.
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


def _spec(name, handler):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


def _meds():
    return _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])


# --- budget exhausted -> disclosure + event ------------------------------------

def test_budget_exhaustion_marks_answer_partial_and_emits_truncated_event():
    # max_tool_calls=1: the first turn spends the budget on a tool, the second is
    # offered no tools and must answer -> the answer is budget-forced (partial).
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("The patient is on Warfarin.")], "end_turn"),
    ])
    agent = ClaudeAgent(
        creator, RecordingBoundary({}), extra_tools=[_meds()], max_tool_calls=1
    )

    events = []
    answer, _ = agent.run_turn("what meds?", pid=42, on_event=events.append)

    assert "lookup limit" in answer.lower()
    assert any(e.get("type") == "truncated" and e.get("reason") == "tool_budget" for e in events)
    # emitted exactly once
    assert sum(1 for e in events if e.get("type") == "truncated") == 1


def test_clinical_answer_text_is_preserved_alongside_the_notice():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("The patient is on Warfarin.")], "end_turn"),
    ])
    agent = ClaudeAgent(
        creator, RecordingBoundary({}), extra_tools=[_meds()], max_tool_calls=1
    )

    answer = agent.run("what meds?", pid=42)

    assert "The patient is on Warfarin." in answer   # gated clinical text intact
    assert "lookup limit" in answer.lower()          # notice appended, not replacing


# --- natural under-budget answer -> unchanged ----------------------------------

def test_natural_answer_under_budget_is_not_marked_partial():
    # Default budget (8); one tool then a natural answer -> not truncated.
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("The patient is on Warfarin.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_meds()])

    events = []
    answer, _ = agent.run_turn("what meds?", pid=42, on_event=events.append)

    assert "lookup limit" not in answer.lower()
    assert not any(e.get("type") == "truncated" for e in events)


def test_immediate_answer_no_tools_is_not_marked_partial():
    creator = ScriptedCreator([_resp([_text("The patient is stable.")], "end_turn")])
    agent = ClaudeAgent(creator, RecordingBoundary({}))

    answer = agent.run("how is the patient?", pid=42)

    assert "lookup limit" not in answer.lower()


# --- backward compatibility ----------------------------------------------------

def test_exhausted_budget_without_on_event_appends_notice_and_does_not_crash():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("The patient is on Warfarin.")], "end_turn"),
    ])
    agent = ClaudeAgent(
        creator, RecordingBoundary({}), extra_tools=[_meds()], max_tool_calls=1
    )

    answer = agent.run("what meds?", pid=42)   # on_event defaults to None

    assert "lookup limit" in answer.lower()
