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


# --- exactly-once execution under span failures (a double-run double-bills Claude) ---

class _CountingRaisingAgent:
    def __init__(self, calls):
        self._calls = calls

    def run(self, question, pid):
        self._calls.append(1)
        raise RuntimeError("anthropic 500 — expensive to retry")


def test_agent_error_inside_a_working_span_runs_the_agent_exactly_once():
    # A working span (nullcontext) with an agent that raises: the agent's own
    # failure must NOT trigger a re-run. It runs once, and the error is masked 502.
    calls = []
    body = json.dumps({"pid": 3, "question": "hi"}).encode()

    status, out = process_ask(
        "Bearer t", body, lambda pid, jwt: _CountingRaisingAgent(calls), tracer=RecordingTracer()
    )

    assert status == 502
    assert out == {"error": "the assistant is unavailable"}
    assert len(calls) == 1  # NOT double-run


class _ExitFailSpan:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        raise RuntimeError("span __exit__ failed")


class _ExitFailTracer:
    def turn(self, metadata):
        return _ExitFailSpan()


def test_span_exit_error_is_swallowed_and_agent_runs_once():
    calls = []

    class _A:
        def run(self, question, pid):
            calls.append(1)
            return "ok"

    body = json.dumps({"pid": 3, "question": "hi"}).encode()
    status, out = process_ask("Bearer t", body, lambda pid, jwt: _A(), tracer=_ExitFailTracer())

    assert status == 200
    assert out == {"answer": "ok"}
    assert len(calls) == 1


class _EnterFailSpan:
    def __enter__(self):
        raise RuntimeError("span __enter__ failed")

    def __exit__(self, *exc):
        return False


class _EnterFailTracer:
    def turn(self, metadata):
        return _EnterFailSpan()


def test_span_enter_error_still_runs_agent_exactly_once():
    calls = []

    class _A:
        def run(self, question, pid):
            calls.append(1)
            return "ok"

    body = json.dumps({"pid": 3, "question": "hi"}).encode()
    status, out = process_ask("Bearer t", body, lambda pid, jwt: _A(), tracer=_EnterFailTracer())

    assert status == 200
    assert out == {"answer": "ok"}
    assert len(calls) == 1
