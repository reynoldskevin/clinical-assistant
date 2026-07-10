"""T20 acceptance tests (LOCKED) — search_chart tool (chart boundary + ToolSpec).

Free-text chart search. ``query`` is a REQUIRED model input; ``limit`` is optional.
read.php returns a BARE ARRAY of snippet rows (decision #12 — the fake mirrors the
real endpoint shape). No live API call, no running OpenEMR: injected fake opener.
"""
import io
import json

import pytest

from factory import build_chart_boundary, build_search_tool


class _FakeResponse:
    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._buf.read()


def test_chart_boundary_search_posts_op_query_and_limit():
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data)
        return _FakeResponse(b'[{"ref": "pnote:1", "source_type": "note", "snippet": "chest pain"}]')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt-s", opener=opener)
    out = boundary.search_chart(42, "chest pain", limit=5)

    assert captured["url"] == "http://openemr/read.php"
    assert captured["auth"] == "Bearer jwt-s"
    assert captured["body"] == {"op": "search_chart", "pid": 42, "params": {"query": "chest pain", "limit": 5}}
    assert out == [{"ref": "pnote:1", "source_type": "note", "snippet": "chest pain"}]


def test_chart_boundary_search_has_a_default_limit():
    captured = {}

    def opener(request, timeout=None):
        captured["body"] = json.loads(request.data)
        return _FakeResponse(b"[]")

    boundary = build_chart_boundary("http://openemr/read.php", "jwt", opener=opener)
    boundary.search_chart(42, "headache")

    assert captured["body"]["op"] == "search_chart"
    assert captured["body"]["params"]["query"] == "headache"
    assert captured["body"]["params"]["limit"] == 20


def test_boundary_search_propagates_http_errors():
    def opener(request, timeout=None):
        raise OSError("403 Forbidden")

    boundary = build_chart_boundary("http://openemr/read.php", "bad", opener=opener)
    with pytest.raises(OSError):
        boundary.search_chart(7, "x")


def test_search_tool_is_wellformed_requires_query_and_dispatches():
    calls = []

    class FakeChartBoundary:
        def search_chart(self, pid, query, limit=20):
            calls.append((pid, query, limit))
            return [{"ref": "pnote:1"}]

    spec = build_search_tool(FakeChartBoundary())

    assert spec["name"] == "search_chart"
    assert spec["description"]
    assert spec["input_schema"]["type"] == "object"
    # query is REQUIRED; limit is optional.
    assert spec["input_schema"]["properties"]["query"]["type"] == "string"
    assert spec["input_schema"]["required"] == ["query"]
    assert "limit" in spec["input_schema"]["properties"]
    assert callable(spec["handler"])

    out = spec["handler"](42, {"query": "chest pain", "limit": 3})
    assert out == [{"ref": "pnote:1"}]
    assert calls == [(42, "chest pain", 3)]

    # limit omitted -> defaults to 20 (whether the handler passes it explicitly or
    # relies on the boundary's default, the fake records 20).
    spec["handler"](7, {"query": "x"})
    assert calls[-1] == (7, "x", 20)
