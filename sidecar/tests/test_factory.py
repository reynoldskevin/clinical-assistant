"""Tests for the production wiring (factory.py).

No live API call and no running OpenEMR: the anthropic client and the HTTP
opener are injected fakes, so these tests exercise the wiring — request shape,
header forwarding, JSON parsing, error propagation — in isolation.
"""
import io
import json

import pytest

from factory import build_boundary, build_message_creator


class _FakeResponse:
    """Minimal context-manager standing in for an http.client response."""

    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._buf.read()


def test_boundary_posts_pid_with_bearer_and_parses_summary():
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _FakeResponse(b'{"demographics": {"pid": 7}, "problems": []}')

    boundary = build_boundary("http://openemr/summary.php", "jwt-abc", opener=opener)
    summary = boundary(7)

    assert captured["url"] == "http://openemr/summary.php"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer jwt-abc"
    assert captured["body"] == {"pid": 7}
    assert summary == {"demographics": {"pid": 7}, "problems": []}


def test_boundary_propagates_http_errors():
    def opener(request, timeout=None):
        raise OSError("403 Forbidden")

    boundary = build_boundary("http://openemr/summary.php", "bad-jwt", opener=opener)
    with pytest.raises(OSError):
        boundary(7)


def test_boundary_rejects_non_object_summary():
    def opener(request, timeout=None):
        return _FakeResponse(b'["not", "an", "object"]')

    boundary = build_boundary("http://openemr/summary.php", "jwt", opener=opener)
    with pytest.raises(ValueError):
        boundary(7)


def test_message_creator_wraps_injected_client_and_defaults_model():
    class FakeMessages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return {"ok": True}

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    client = FakeClient()
    create = build_message_creator(client=client, model="claude-opus-4-8")

    # Caller omits model -> the factory supplies the default.
    result = create(max_tokens=16, system="s", tools=[], messages=[])
    assert result == {"ok": True}
    assert client.messages.kwargs["model"] == "claude-opus-4-8"
    assert client.messages.kwargs["max_tokens"] == 16

    # Caller-supplied model is respected.
    create(model="claude-sonnet-4-6", max_tokens=1, system="s", tools=[], messages=[])
    assert client.messages.kwargs["model"] == "claude-sonnet-4-6"
