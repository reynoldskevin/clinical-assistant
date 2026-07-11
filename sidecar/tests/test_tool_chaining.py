"""T21 acceptance tests (LOCKED) — tool chaining + max-tool-calls budget.

Unit tests only: injected fakes, no anthropic SDK, no live API call. Response
objects mimic the SDK Message shape (.content blocks + .stop_reason).
"""
from types import SimpleNamespace

from agent import ClaudeAgent
from observability import TraceCollector


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


def _spec(name, handler, schema=None):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": schema or {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


def test_agent_chains_two_tools_across_iterations_with_fixed_pid():
    # The model lists encounters, then fetches one by the id it saw — a real chain.
    creator = ScriptedCreator([
        _resp([_tool_use("list_encounters", {}, "t1")], "tool_use"),
        _resp([_tool_use("get_encounter", {"encounter_id": 5}, "t2")], "tool_use"),
        _resp([_text("Encounter 5 was a follow-up visit.")], "end_turn"),
    ])
    calls = []
    le = _spec("list_encounters", lambda pid, inp: calls.append(("list", pid)) or [{"encounter": 5}])
    ge = _spec("get_encounter", lambda pid, inp: calls.append(("get", pid, inp.get("encounter_id"))) or {"encounter": 5})

    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[le, ge])
    result = agent.run("Give me the details of the most recent encounter.", pid=42)

    assert result == "Encounter 5 was a follow-up visit."
    # both tools ran, in order, each with the fixed session pid
    assert calls == [("list", 42), ("get", 42, 5)]


def test_max_tool_calls_budget_caps_executions_and_forces_final_answer():
    # A model that keeps calling a tool WHENEVER tools are offered; once the budget
    # is spent the agent must call with no tools, and the model then answers.
    class BudgetCreator:
        def __init__(self):
            self.calls = []

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("tools"):
                return _resp([_tool_use("list_encounters", {}, f"t{len(self.calls)}")], "tool_use")
            return _resp([_text("Final answer from what I have.")], "end_turn")

    creator = BudgetCreator()
    obs = TraceCollector()
    spec = _spec("list_encounters", lambda pid, inp: [{"encounter": 1}])

    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[spec], observer=obs, max_tool_calls=3)
    result = agent.run("keep going forever", pid=42)

    # startswith, not equality: T30 appends a completeness-boundary disclosure on
    # the budget-exhausted path (this is that path). The clinical text is intact.
    assert result.startswith("Final answer from what I have.")
    assert "lookup limit" in result.lower()   # the truncation is surfaced, not silent
    # exactly the budget's worth of tool executions — no more
    assert obs.summary()["tool_calls"] == 3
    # the model calls that offered tools == budget; the final call offered none
    offered = [c for c in creator.calls if c.get("tools")]
    assert len(offered) == 3
    assert creator.calls[-1]["tools"] == []


def test_under_budget_a_normal_chained_turn_is_unaffected():
    creator = ScriptedCreator([
        _resp([_tool_use("list_encounters", {}, "t1")], "tool_use"),
        _resp([_text("You have 1 encounter.")], "end_turn"),
    ])
    obs = TraceCollector()
    spec = _spec("list_encounters", lambda pid, inp: [{"encounter": 5}])

    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[spec], observer=obs, max_tool_calls=8)
    result = agent.run("list encounters", pid=42)

    assert result == "You have 1 encounter."
    assert obs.summary()["tool_calls"] == 1
    # tools were offered on the first call (under budget)
    assert creator.calls[0]["tools"]


def test_budget_default_allows_a_two_tool_chain():
    # With the default budget (unspecified), a 2-tool chain still completes.
    creator = ScriptedCreator([
        _resp([_tool_use("list_encounters", {}, "t1")], "tool_use"),
        _resp([_tool_use("get_encounter", {"encounter_id": 9}, "t2")], "tool_use"),
        _resp([_text("done")], "end_turn"),
    ])
    le = _spec("list_encounters", lambda pid, inp: [{"encounter": 9}])
    ge = _spec("get_encounter", lambda pid, inp: {"encounter": 9})

    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[le, ge])
    assert agent.run("chain please", pid=42) == "done"
