"""Tests for the sidecar HTTP request handling (server.process_ask).

The pure request-processing function is tested directly with a fake
agent-builder, so there are no sockets, no live API call, and no running
OpenEMR. Verifies auth enforcement, input validation, JWT forwarding, the
success shape, and that internal failures never leak to the caller.
"""
import json

from server import process_ask


class _FakeAgent:
    def __init__(self, answer):
        self._answer = answer
        self.run_calls = []

    def run(self, question, pid):
        self.run_calls.append((question, pid))
        return self._answer


def _builder(answer, record=None):
    def build(pid, jwt):
        if record is not None:
            record["pid"] = pid
            record["jwt"] = jwt
        return _FakeAgent(answer)

    return build


def test_valid_request_returns_answer_and_forwards_jwt():
    record = {}
    body = json.dumps({"pid": 3, "question": "What are the active problems?"}).encode()
    status, out = process_ask("Bearer tok-123", body, _builder("Atrial fibrillation.", record))

    assert status == 200
    assert out["answer"] == "Atrial fibrillation."
    assert out["correlation_id"]   # T35: every invocation surfaces a correlation id
    # The forwarded credential and fixed pid reach the agent-builder unchanged.
    assert record == {"pid": 3, "jwt": "tok-123"}


def test_missing_bearer_is_unauthorized():
    body = json.dumps({"pid": 3, "question": "hi"}).encode()
    status, out = process_ask("", body, _builder("x"))
    assert status == 401
    assert "error" in out


def test_empty_bearer_is_unauthorized():
    body = json.dumps({"pid": 3, "question": "hi"}).encode()
    status, _ = process_ask("Bearer    ", body, _builder("x"))
    assert status == 401


def test_invalid_json_is_bad_request():
    status, _ = process_ask("Bearer t", b"not json", _builder("x"))
    assert status == 400


def test_missing_pid_or_question_is_bad_request():
    status_a, _ = process_ask("Bearer t", json.dumps({"question": "hi"}).encode(), _builder("x"))
    status_b, _ = process_ask("Bearer t", json.dumps({"pid": 3}).encode(), _builder("x"))
    status_c, _ = process_ask("Bearer t", json.dumps({"pid": 0, "question": "hi"}).encode(), _builder("x"))
    assert status_a == 400
    assert status_b == 400
    assert status_c == 400


def test_agent_failure_is_not_leaked():
    def exploding_builder(pid, jwt):
        raise RuntimeError("anthropic 500: internal detail that must not leak")

    body = json.dumps({"pid": 3, "question": "hi"}).encode()
    status, out = process_ask("Bearer t", body, exploding_builder)

    assert status == 502
    assert out == {"error": "the assistant is unavailable"}
    assert "internal detail" not in json.dumps(out)
