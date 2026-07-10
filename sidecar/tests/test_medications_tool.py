"""T19 acceptance tests (LOCKED) — get_medications tool (chart boundary + ToolSpec).

The medications tool carries an optional model-supplied ``active_only`` flag and,
like the other list ops, read.php returns a BARE ARRAY (per decision #12 — the
fake response here mirrors the real endpoint shape). No live API call, no running
OpenEMR: the HTTP opener is an injected fake.
"""
import io
import json

import pytest

from factory import build_chart_boundary, build_medications_tool


class _FakeResponse:
    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._buf.read()


def test_chart_boundary_get_medications_posts_op_and_active_only():
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data)
        # read.php returns a BARE ARRAY for get_medications (not a wrapped object).
        return _FakeResponse(b'[{"drug": "Warfarin", "status_conflict": true}]')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt-med", opener=opener)
    out = boundary.get_medications(42, active_only=True)

    assert captured["url"] == "http://openemr/read.php"
    assert captured["auth"] == "Bearer jwt-med"
    assert captured["body"] == {"op": "get_medications", "pid": 42, "params": {"active_only": True}}
    assert out == [{"drug": "Warfarin", "status_conflict": True}]


def test_chart_boundary_get_medications_defaults_active_only_false():
    captured = {}

    def opener(request, timeout=None):
        captured["body"] = json.loads(request.data)
        return _FakeResponse(b"[]")

    boundary = build_chart_boundary("http://openemr/read.php", "jwt", opener=opener)
    boundary.get_medications(42)

    assert captured["body"] == {"op": "get_medications", "pid": 42, "params": {"active_only": False}}


def test_boundary_get_medications_propagates_http_errors():
    def opener(request, timeout=None):
        raise OSError("403 Forbidden")

    boundary = build_chart_boundary("http://openemr/read.php", "bad", opener=opener)
    with pytest.raises(OSError):
        boundary.get_medications(7)


def test_medications_tool_is_wellformed_and_dispatches_active_only():
    calls = []

    class FakeChartBoundary:
        def get_medications(self, pid, active_only=False):
            calls.append((pid, active_only))
            return [{"drug": "X"}]

    spec = build_medications_tool(FakeChartBoundary())

    assert spec["name"] == "get_medications"
    assert spec["description"]
    assert spec["input_schema"]["type"] == "object"
    # active_only is an OPTIONAL model input (boolean), not required.
    assert "active_only" in spec["input_schema"]["properties"]
    assert spec["input_schema"]["properties"]["active_only"]["type"] == "boolean"
    assert "active_only" not in spec["input_schema"].get("required", [])
    assert callable(spec["handler"])

    out = spec["handler"](42, {"active_only": True})
    assert out == [{"drug": "X"}]
    assert calls == [(42, True)]

    # Omitted -> defaults to False (all meds).
    spec["handler"](7, {})
    assert calls[-1] == (7, False)
