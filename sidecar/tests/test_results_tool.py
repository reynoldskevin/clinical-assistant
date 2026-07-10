"""T18 acceptance tests (LOCKED) — get_results tool (chart boundary + ToolSpec).

Production wiring for the lab/diagnostic results tool: the ChartBoundary gains a
get_results(pid) method (POSTs op=get_results to read.php), and build_results_tool
turns it into the ToolSpec the agent registers. Its handler is invoked with the
FIXED session pid. No live API call, no running OpenEMR: injected fakes.
"""
import io
import json

import pytest

from factory import build_chart_boundary, build_results_tool


class _FakeResponse:
    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._buf.read()


def test_chart_boundary_get_results_posts_op_with_bearer():
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data)
        # read.php returns the provider result directly — a BARE ARRAY for
        # get_results (NOT wrapped in an object), matching what the live endpoint sends.
        return _FakeResponse(b'[{"result_code": "4548-4"}, {"result_code": "2339-0"}]')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt-xyz", opener=opener)
    out = boundary.get_results(42)

    assert captured["url"] == "http://openemr/read.php"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer jwt-xyz"
    assert captured["body"] == {"op": "get_results", "pid": 42, "params": {}}
    assert out == [{"result_code": "4548-4"}, {"result_code": "2339-0"}]


def test_boundary_get_results_propagates_http_errors():
    def opener(request, timeout=None):
        raise OSError("403 Forbidden")

    boundary = build_chart_boundary("http://openemr/read.php", "bad", opener=opener)
    with pytest.raises(OSError):
        boundary.get_results(7)


def test_results_tool_is_wellformed_and_dispatches_to_boundary():
    calls = []

    class FakeChartBoundary:
        def get_results(self, pid):
            calls.append(("results", pid))
            return {"results": []}

    spec = build_results_tool(FakeChartBoundary())

    assert spec["name"] == "get_results"
    assert spec["description"]
    assert spec["input_schema"]["type"] == "object"
    assert callable(spec["handler"])

    # Handler is called with the fixed session pid; model input is irrelevant here.
    out = spec["handler"](42, {})
    assert out == {"results": []}
    assert calls == [("results", 42)]
