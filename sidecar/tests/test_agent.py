"""T12 acceptance tests (LOCKED) for the sidecar ClaudeAgent tool-use loop.

Unit tests only: the Claude message-creator and the boundary caller are injected
fakes, so there is no anthropic SDK import and no live API call. Response objects
mimic the SDK Message shape (.content blocks + .stop_reason).
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ScriptedCreator:
    """A fake message-creator that returns scripted responses and records calls."""
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


def test_single_tool_turn_returns_final_text():
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {}, "tu1")], "tool_use"),
        _resp([_text("The patient is stable.")], "end_turn"),
    ])
    boundary = RecordingBoundary({"demographics": {"pid": 42}})
    agent = ClaudeAgent(message_creator=creator, boundary=boundary)

    result = agent.run("How is the patient doing?", pid=42)

    assert result == "The patient is stable."
    assert boundary.pids == [42]                        # boundary called with the session pid
    # the second creator call was fed a tool_result referencing the tool_use id
    trs = _tool_results(creator.calls[1]["messages"])
    assert any(tr["tool_use_id"] == "tu1" for tr in trs)


def test_no_tool_use_returns_direct_answer():
    creator = ScriptedCreator([_resp([_text("Hello, how can I help?")], "end_turn")])
    boundary = RecordingBoundary({})
    agent = ClaudeAgent(creator, boundary)

    assert agent.run("Hi", pid=42) == "Hello, how can I help?"
    assert boundary.pids == []                          # tool never invoked


def test_model_supplied_pid_is_ignored_fixed_session_pid_used():
    # the model tries to pull a DIFFERENT patient; the sidecar must ignore it
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {"pid": 99}, "tu1")], "tool_use"),
        _resp([_text("done")], "end_turn"),
    ])
    boundary = RecordingBoundary({"demographics": {"pid": 42}})
    agent = ClaudeAgent(creator, boundary)

    agent.run("Show me patient 99's chart", pid=42)

    assert boundary.pids == [42]                         # NOT 99 — model cannot redirect


def test_tool_catalog_is_wellformed_and_passed_to_creator():
    creator = ScriptedCreator([_resp([_text("x")], "end_turn")])
    ClaudeAgent(creator, RecordingBoundary({}), model="claude-opus-4-8").run("hi", pid=1)

    call = creator.calls[0]
    assert call["model"] == "claude-opus-4-8"
    assert call["messages"][0]["role"] == "user"
    tool = next(t for t in call["tools"] if t["name"] == "get_patient_summary")
    assert tool["description"]
    assert tool["input_schema"]["type"] == "object"


def test_tool_result_content_carries_the_summary():
    summary = {"demographics": {"pid": 42, "fname": "Jane"}, "problems": []}
    creator = ScriptedCreator([
        _resp([_tool_use("get_patient_summary", {}, "tuX")], "tool_use"),
        _resp([_text("ok")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary(summary))
    agent.run("summarize", pid=42)

    trs = _tool_results(creator.calls[1]["messages"])
    assert len(trs) == 1
    # content is JSON-serialized summary (string or list-of-text-blocks both acceptable)
    raw = trs[0]["content"]
    text = raw if isinstance(raw, str) else json.dumps(raw)
    assert "Jane" in text
