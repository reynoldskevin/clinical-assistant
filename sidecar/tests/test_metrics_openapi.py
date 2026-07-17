"""T74 contract tests (LOCKED) — GET /metrics is documented and matches the server.

`GET /metrics` (T73) must be described in the published OpenAPI spec with the
EXACT response shape the handler returns, and listed in the README. These tests
pin the spec's `/metrics` 200 schema against a live round-trip through the real
`make_handler` (spec⇄server contract, decision #12), so the doc can't drift from
the endpoint.
"""
import http.client
import json
import os
import threading

from http.server import ThreadingHTTPServer

import yaml

from events import (
    EXTRACTION_FIELD,
    INGESTION_COMPLETE,
    RETRIEVAL_HIT,
    RETRIEVAL_MISS,
    WORKER_HANDOFF,
    log_event,
)
from metrics_buffer import EventBuffer
from server import make_handler

_HERE = os.path.dirname(__file__)
SPEC_PATH = os.path.join(_HERE, "..", "openapi.yaml")
README_PATH = os.path.join(_HERE, "..", "..", "README.md")


# --- spec helpers ------------------------------------------------------------

def _spec():
    with open(SPEC_PATH) as fh:
        return yaml.safe_load(fh)


def _resolve(spec, node):
    if isinstance(node, dict) and "$ref" in node:
        cur = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur[part]
        return cur
    return node


def _metrics_200_schema(spec):
    node = spec["paths"]["/metrics"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    return _resolve(spec, node)


def _props(spec, schema):
    return {k: _resolve(spec, v) for k, v in (schema.get("properties") or {}).items()}


# --- real server body --------------------------------------------------------

def _agent_builder(pid, jwt):
    raise AssertionError("agent builder must not be called for /metrics")


def _real_metrics_body():
    buf = EventBuffer(maxlen=100)
    for r in (
        log_event(INGESTION_COMPLETE, "c", document_id=1, doc_type="lab_pdf"),
        log_event(EXTRACTION_FIELD, "c", field="a", outcome="ok"),
        log_event(EXTRACTION_FIELD, "c", field="b", outcome="unsupported"),
        log_event(RETRIEVAL_HIT, "c", count=2),
        log_event(RETRIEVAL_MISS, "c"),
        log_event(WORKER_HANDOFF, "c", from_="supervisor", to="evidence_retriever"),
    ):
        buf.add(r)
    handler = make_handler(_agent_builder, "*", None, None, None, event_buffer=buf)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("GET", "/metrics")
        res = conn.getresponse()
        body = json.loads(res.read() or b"{}")
        conn.close()
        return body
    finally:
        server.shutdown()


# --- 1. the spec documents GET /metrics, unauthenticated ---------------------

def test_spec_documents_metrics_get_without_auth():
    spec = _spec()
    assert "/metrics" in spec["paths"], "spec does not document /metrics"
    op = spec["paths"]["/metrics"]["get"]
    assert "200" in op["responses"]
    # unauthenticated like /health and /ready — no security requirement
    assert not op.get("security"), "/metrics must not require auth"


# --- 2. the documented response shape equals the real server body ------------

def test_metrics_top_level_shape_matches_server():
    spec = _spec()
    schema = _metrics_200_schema(spec)
    body = _real_metrics_body()
    spec_top = set((schema.get("properties") or {}).keys())
    assert spec_top == set(body.keys()) == {"panels", "alerts", "window"}


def test_metrics_panels_subschema_matches_server():
    spec = _spec()
    panels_schema = _props(spec, _metrics_200_schema(spec))["panels"]
    panels_props = _props(spec, panels_schema)
    body_panels = _real_metrics_body()["panels"]

    assert set(panels_props) == set(body_panels) == {
        "ingestion_count", "extraction", "retrieval", "routing",
    }
    assert set(panels_props["extraction"].get("properties") or {}) == set(body_panels["extraction"]) == {
        "total", "ok", "field_pass_rate", "by_outcome",
    }
    assert set(panels_props["retrieval"].get("properties") or {}) == set(body_panels["retrieval"]) == {
        "hits", "misses", "hit_rate",
    }


def test_metrics_alerts_and_window_subschema_matches_server():
    spec = _spec()
    top = _props(spec, _metrics_200_schema(spec))
    body = _real_metrics_body()

    alerts_props = _props(spec, top["alerts"])
    assert set(alerts_props) == set(body["alerts"]) == {"extraction_failure"}
    assert set(alerts_props["extraction_failure"].get("properties") or {}) == set(
        body["alerts"]["extraction_failure"]
    ) == {"firing", "rate", "failed", "total"}

    window_props = top["window"].get("properties") or {}
    assert set(window_props) == set(body["window"]) == {"events", "buffer_max"}


# --- 3. README documents the endpoint ----------------------------------------

def test_readme_documents_metrics_endpoint():
    with open(README_PATH) as fh:
        assert "/metrics" in fh.read(), "README does not document the /metrics endpoint"
