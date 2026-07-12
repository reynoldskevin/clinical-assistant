"""T22 acceptance tests (LOCKED) — multi-turn: agent.run_turn + process_ask.

Unit tests only: injected fakes, no anthropic SDK, no live API call.
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent
from conversation import ConversationStore
from server import process_ask


def _text(t):
    return SimpleNamespace(type="text", text=t)


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


def test_run_turn_returns_answer_and_conversation_history():
    creator = ScriptedCreator([_resp([_text("Your blood pressure is 120/80.")], "end_turn")])
    agent = ClaudeAgent(creator, RecordingBoundary({}))

    answer, history = agent.run_turn("What is my blood pressure?", pid=42)

    assert answer == "Your blood pressure is 120/80."
    assert history[0]["role"] == "user"
    assert "What is my blood pressure?" in json.dumps(history[0])
    assert any(m["role"] == "assistant" for m in history)  # the reply is retained


def test_second_turn_carries_prior_context_to_the_model():
    creator = ScriptedCreator([
        _resp([_text("Your blood pressure is 120/80.")], "end_turn"),
        _resp([_text("Yes, 120/80 is within the normal range.")], "end_turn"),
    ])
    agent = ClaudeAgent(creator, RecordingBoundary({}))

    _, history = agent.run_turn("What is my blood pressure?", pid=42)
    answer2, _ = agent.run_turn("Is that normal?", pid=42, history=history)

    assert answer2 == "Yes, 120/80 is within the normal range."
    # The 2nd model call must have seen BOTH the earlier turn and the follow-up.
    second_call_messages = json.dumps(creator.calls[1]["messages"])
    assert "What is my blood pressure?" in second_call_messages
    assert "120/80" in second_call_messages
    assert "Is that normal?" in second_call_messages


def test_run_still_returns_a_plain_string():
    creator = ScriptedCreator([_resp([_text("hello")], "end_turn")])
    assert ClaudeAgent(creator, RecordingBoundary({})).run("hi", pid=1) == "hello"


class _ConvAgent:
    """A fake agent that echoes and accumulates conversation history."""

    def run_turn(self, question, pid, history=None):
        hist = list(history or [])
        hist.append({"role": "user", "content": question})
        hist.append({"role": "assistant", "content": f"answer to {question}"})
        return f"answer to {question}", hist


def _builder(pid_seen=None):
    def build(pid, jwt):
        if pid_seen is not None:
            pid_seen.append((pid, jwt))
        return _ConvAgent()

    return build


def test_process_ask_with_store_carries_context_across_calls():
    store = ConversationStore(ttl_seconds=600.0, clock=lambda: 0.0)

    body1 = json.dumps({"pid": 3, "question": "first question", "conversation_id": "c1"}).encode()
    status1, out1 = process_ask("Bearer t", body1, _builder(), store=store)
    assert status1 == 200
    assert out1["answer"] == "answer to first question"

    body2 = json.dumps({"pid": 3, "question": "second question", "conversation_id": "c1"}).encode()
    status2, out2 = process_ask("Bearer t", body2, _builder(), store=store)
    assert status2 == 200

    # After both turns the persisted history holds BOTH questions (context carried).
    persisted = json.dumps(store.history("c1", 3))
    assert "first question" in persisted
    assert "second question" in persisted


def test_process_ask_conversation_is_pid_scoped():
    store = ConversationStore(ttl_seconds=600.0, clock=lambda: 0.0)
    body = json.dumps({"pid": 3, "question": "patient 3 context", "conversation_id": "c1"}).encode()
    process_ask("Bearer t", body, _builder(), store=store)

    # The same conversation_id under a different pid must NOT see patient 3's history.
    assert store.history("c1", 999) is None


def test_process_ask_without_store_is_stateless():
    # No store -> the plain run() path (backward compatible with test_server.py).
    class RunAgent:
        def run(self, question, pid):
            return "stateless answer"

    body = json.dumps({"pid": 3, "question": "hi"}).encode()
    status, out = process_ask("Bearer t", body, lambda pid, jwt: RunAgent())
    assert status == 200
    assert out["answer"] == "stateless answer"   # T35: body also carries an additive correlation_id
