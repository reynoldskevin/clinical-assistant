"""T17 acceptance tests (LOCKED) — multi-tool dispatch in ClaudeAgent.

The agent gains an injectable tool registry (`extra_tools`) so new chart tools
(list_encounters, get_encounter, and everything T18-T20 adds) can be wired in
without touching the loop. Each extra tool is a spec dict
``{name, description, input_schema, handler}`` where ``handler(pid, tool_input)``
returns a JSON-serializable dict. The session pid is FIXED (from the token) and
passed to every handler; the model's ``tool_input`` is passed through but can
never redirect the pid. The built-in get_patient_summary path (T12) is unchanged.

Unit tests only: injected fakes, no anthropic SDK, no live API call.
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
        self.pids = []

    def __call__(self, pid):
        self.pids.append(pid)
        return self.summary


def _tool_results(messages):
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out.append(block)
    return out


def _spec(name, handler, schema=None):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": schema or {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


def test_list_encounters_tool_dispatches_to_handler_with_fixed_pid():
    calls = []

    def handler(pid, tool_input):
        calls.append((pid, tool_input))
        return {"encounters": [{"encounter": 5, "date": "2021-01-01"}]}

    creator = ScriptedCreator([
        _resp([_tool_use("list_encounters", {}, "tu1")], "tool_use"),
        _resp([_text("You have 1 encounter.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("list_encounters", handler)])

    result = agent.run("list this patient's encounters", pid=42)

    assert result == "You have 1 encounter."
    assert calls == [(42, {})]                              # session pid, not from the model
    trs = _tool_results(creator.calls[1]["messages"])
    assert any(tr["tool_use_id"] == "tu1" for tr in trs)
    assert "encounter" in (trs[0]["content"] if isinstance(trs[0]["content"], str) else str(trs[0]["content"]))


def test_get_encounter_handler_gets_fixed_pid_and_model_input():
    seen = []

    def handler(pid, tool_input):
        seen.append((pid, tool_input))
        return {"encounter": tool_input.get("encounter_id")}

    schema = {
        "type": "object",
        "properties": {"encounter_id": {"type": "integer"}},
        "required": ["encounter_id"],
        "additionalProperties": False,
    }
    creator = ScriptedCreator([
        # The model even tries to smuggle a different pid; the handler still gets 42.
        _resp([_tool_use("get_encounter", {"encounter_id": 5, "pid": 99}, "tuG")], "tool_use"),
        _resp([_text("Encounter 5 was a follow-up.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("get_encounter", handler, schema)])

    agent.run("show me encounter 5", pid=42)

    assert seen == [(42, {"encounter_id": 5, "pid": 99})]   # pid arg fixed at 42


def test_extra_tools_appear_in_catalog_alongside_builtin_without_handler():
    creator = ScriptedCreator([_resp([_text("hi")], "end_turn")])
    agent = ClaudeAgent(
        creator,
        RecordingBoundary({}),
        extra_tools=[_spec("list_encounters", lambda pid, inp: {}), _spec("get_encounter", lambda pid, inp: {})],
    )
    agent.run("hello", pid=1)

    tools = creator.calls[0]["tools"]
    names = {t["name"] for t in tools}
    assert {"get_patient_summary", "list_encounters", "get_encounter"} <= names
    # The handler is an internal detail and must NOT be sent to the API.
    assert all("handler" not in t for t in tools)
    for t in tools:
        assert t["input_schema"]["type"] == "object"


def test_unknown_tool_still_returns_a_tool_error():
    creator = ScriptedCreator([
        _resp([_tool_use("delete_everything", {}, "tuX")], "tool_use"),
        _resp([_text("I can't do that.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("list_encounters", lambda pid, inp: {})])

    agent.run("delete the database", pid=1)

    trs = _tool_results(creator.calls[1]["messages"])
    assert len(trs) == 1
    assert trs[0]["is_error"] is True


def test_builtin_summary_still_works_when_extra_tools_present():
    boundary = RecordingBoundary({"demographics": {"pid": 42}})
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {}, "tu1")], "tool_use"),
        _resp([_text("The patient is stable.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, boundary, extra_tools=[_spec("list_encounters", lambda pid, inp: {})])

    assert agent.run("summarize the chart", pid=42) == "The patient is stable."
    assert boundary.pids == [42]                            # summary boundary still called


def test_handler_failure_is_reported_as_tool_error_not_crash():
    def boom(pid, tool_input):
        raise RuntimeError("boundary 500")

    creator = ScriptedCreator([
        _resp([_tool_use("list_encounters", {}, "tuE")], "tool_use"),
        _resp([_text("The encounter list is unavailable.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[_spec("list_encounters", boom)])

    # The loop must not crash; the model gets an error tool_result and can respond.
    result = agent.run("list encounters", pid=42)

    # startswith, not equality: T31 appends a partial-failure disclosure on the
    # failed-tool path (this is that path). The clinical text is intact.
    assert result.startswith("The encounter list is unavailable.")
    assert "may be incomplete" in result.lower()   # the failure is surfaced, not silent
    trs = _tool_results(creator.calls[1]["messages"])
    assert trs[0]["is_error"] is True
