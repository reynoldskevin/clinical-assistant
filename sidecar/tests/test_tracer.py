"""obs-1 acceptance tests (LOCKED) — Braintrust conversation/patient tagging.

The tracer wraps each agent turn in a span carrying {conversation_id, pid} so the
auto-logged Claude calls group by conversation + patient. It is optional and
guarded: observability must NEVER break the request path. No live braintrust here
(the venv has no braintrust, so build_tracer's keyed path exercises the fallback).
"""
import contextlib
import json

from factory import build_tracer
from observability import NullTracer
from server import process_ask


def test_null_tracer_turn_is_a_noop_context_manager():
    with NullTracer().turn({"pid": 1, "conversation_id": "c1"}):
        pass  # no error, no output, no side effects


class RecordingTracer:
    """A tracer that records the metadata it is asked to open a turn with."""

    def __init__(self):
        self.turns = []

    def turn(self, metadata):
        self.turns.append(metadata)
        return contextlib.nullcontext()


class _MultiTurnAgent:
    def run_turn(self, question, pid, history=None):
        return "answer", list(history or []) + [{"role": "user", "content": question}]


class _StatelessAgent:
    def run(self, question, pid):
        return "answer"


def test_process_ask_tags_the_turn_with_pid_and_conversation_id():
    from conversation import ConversationStore

    tracer = RecordingTracer()
    store = ConversationStore(ttl_seconds=600.0, clock=lambda: 0.0)
    body = json.dumps({"pid": 7, "question": "hi", "conversation_id": "c9"}).encode()

    status, out = process_ask("Bearer t", body, lambda pid, jwt: _MultiTurnAgent(), store=store, tracer=tracer)

    assert status == 200
    assert out == {"answer": "answer"}
    assert len(tracer.turns) == 1
    assert tracer.turns[0]["pid"] == 7
    assert tracer.turns[0]["conversation_id"] == "c9"


def test_process_ask_single_turn_tags_pid():
    tracer = RecordingTracer()
    body = json.dumps({"pid": 3, "question": "hi"}).encode()

    status, out = process_ask("Bearer t", body, lambda pid, jwt: _StatelessAgent(), tracer=tracer)

    assert status == 200
    assert tracer.turns[0]["pid"] == 3


def test_a_failing_tracer_never_breaks_the_request():
    class FailingTracer:
        def turn(self, metadata):
            raise RuntimeError("tracing backend is down")

    body = json.dumps({"pid": 3, "question": "hi"}).encode()
    status, out = process_ask("Bearer t", body, lambda pid, jwt: _StatelessAgent(), tracer=FailingTracer())

    assert status == 200
    assert out == {"answer": "answer"}


def test_build_tracer_is_a_noop_without_braintrust_key(monkeypatch):
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    tracer = build_tracer()
    with tracer.turn({"pid": 1, "conversation_id": "c1"}):
        pass  # no braintrust configured -> no-op, must not raise


def test_build_tracer_falls_back_safely_when_key_set_but_lib_absent(monkeypatch):
    # braintrust is NOT installed in the sidecar venv, so the keyed path must
    # degrade to a safe no-op rather than raising.
    monkeypatch.setenv("BRAINTRUST_API_KEY", "sk-test")
    tracer = build_tracer()
    with tracer.turn({"pid": 1, "conversation_id": "c1"}):
        pass  # must not raise
