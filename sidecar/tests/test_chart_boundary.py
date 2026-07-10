"""T17 acceptance tests (LOCKED) — chart boundary + encounter ToolSpecs (factory).

The production wiring for the two new tools: a single operation-dispatched HTTP
boundary (`build_chart_boundary`) that POSTs ``{op, pid, params}`` to read.php
with the forwarded Bearer JWT, and `build_encounter_tools` which turns that
boundary into the ToolSpecs the agent registers. No live API call and no running
OpenEMR: the HTTP opener is an injected fake.
"""
import io
import json

import pytest

from factory import build_chart_boundary, build_encounter_tools


class _FakeResponse:
    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._buf.read()


def test_list_encounters_posts_op_and_pid_with_bearer():
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data)
        # read.php returns the provider result directly — a BARE ARRAY for
        # list_encounters (NOT wrapped in an object). Regression for the contract
        # bug where the boundary rejected arrays as "non-object result".
        return _FakeResponse(b'[{"encounter": 5}, {"encounter": 4}]')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt-abc", opener=opener)
    out = boundary.list_encounters(42)

    assert captured["url"] == "http://openemr/read.php"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer jwt-abc"
    assert captured["body"] == {"op": "list_encounters", "pid": 42, "params": {}}
    assert out == [{"encounter": 5}, {"encounter": 4}]


def test_get_encounter_posts_encounter_id_in_params():
    captured = {}

    def opener(request, timeout=None):
        captured["body"] = json.loads(request.data)
        return _FakeResponse(b'{"encounter": 5, "reason": "follow-up"}')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt", opener=opener)
    out = boundary.get_encounter(42, 5)

    assert captured["body"] == {"op": "get_encounter", "pid": 42, "params": {"encounter_id": 5}}
    assert out == {"encounter": 5, "reason": "follow-up"}


def test_summary_op_is_available_on_the_chart_boundary():
    captured = {}

    def opener(request, timeout=None):
        captured["body"] = json.loads(request.data)
        return _FakeResponse(b'{"demographics": {"pid": 42}}')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt", opener=opener)
    boundary.summary(42)

    assert captured["body"] == {"op": "summary", "pid": 42, "params": {}}


def test_boundary_propagates_http_errors():
    def opener(request, timeout=None):
        raise OSError("403 Forbidden")

    boundary = build_chart_boundary("http://openemr/read.php", "bad-jwt", opener=opener)
    with pytest.raises(OSError):
        boundary.list_encounters(7)


def test_encounter_tools_are_wellformed_and_dispatch_to_boundary():
    calls = []

    class FakeChartBoundary:
        def list_encounters(self, pid):
            calls.append(("list", pid))
            return {"encounters": []}

        def get_encounter(self, pid, encounter_id):
            calls.append(("get", pid, encounter_id))
            return {"encounter": encounter_id}

    tools = build_encounter_tools(FakeChartBoundary())
    by_name = {t["name"]: t for t in tools}

    assert set(by_name) == {"list_encounters", "get_encounter"}
    for spec in tools:
        assert spec["description"]
        assert spec["input_schema"]["type"] == "object"
        assert callable(spec["handler"])
    # get_encounter must require an encounter_id from the model.
    assert by_name["get_encounter"]["input_schema"]["required"] == ["encounter_id"]

    list_out = by_name["list_encounters"]["handler"](42, {})
    get_out = by_name["get_encounter"]["handler"](42, {"encounter_id": 9})

    assert list_out == {"encounters": []}
    assert get_out == {"encounter": 9}
    assert calls == [("list", 42), ("get", 42, 9)]
