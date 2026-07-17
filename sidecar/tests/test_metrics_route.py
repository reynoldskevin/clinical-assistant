"""T73 acceptance tests (LOCKED) — over-the-socket GET /metrics.

Boots the real ``make_handler`` on a loopback ephemeral port (mirrors
``test_extract_route.py``) and drives it with ``http.client`` to prove the
``/metrics`` route is wired into ``do_GET``: it folds a buffer of REAL emitted
events through the merged ``panels``/``alerts`` and returns the panels + the
extraction-failure alert + a window summary, unauthenticated like ``/ready``.

The buffer is populated from real ``events.log_event`` records (producer →
buffer → handler JSON), so the payload shape is a genuine round-trip, not a
hand-rolled fake (decision #12).
"""
import http.client
import json
import threading

from http.server import ThreadingHTTPServer

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


def _agent_builder(pid, jwt):  # unused by /metrics, required by make_handler
    raise AssertionError("agent builder must not be called for /metrics")


def _serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get(port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        res = conn.getresponse()
        return res.status, json.loads(res.read() or b"{}")
    finally:
        conn.close()


def _populate(buffer, *, ok, unsupported):
    """Fill the buffer with REAL emitted event records."""
    records = [log_event(INGESTION_COMPLETE, "c", document_id=1, doc_type="lab_pdf")]
    records += [log_event(EXTRACTION_FIELD, "c", field=f"o{i}", outcome="ok") for i in range(ok)]
    records += [log_event(EXTRACTION_FIELD, "c", field=f"u{i}", outcome="unsupported") for i in range(unsupported)]
    records += [
        log_event(RETRIEVAL_HIT, "c", count=2),
        log_event(RETRIEVAL_MISS, "c"),
        log_event(WORKER_HANDOFF, "c", from_="supervisor", to="evidence_retriever"),
    ]
    for r in records:
        buffer.add(r)
    return buffer


def _handler_with(buffer):
    return make_handler(_agent_builder, "*", None, None, None, event_buffer=buffer)


def test_metrics_returns_panels_alerts_and_window():
    buf = _populate(EventBuffer(maxlen=100), ok=6, unsupported=1)
    server = _serve(_handler_with(buf))
    try:
        status, body = _get(server.server_address[1], "/metrics")
    finally:
        server.shutdown()

    assert status == 200
    assert body["panels"]["ingestion_count"] == 1
    assert body["panels"]["extraction"]["total"] == 7
    assert body["panels"]["extraction"]["ok"] == 6
    assert body["panels"]["retrieval"]["hits"] == 1
    assert body["panels"]["retrieval"]["misses"] == 1
    assert body["panels"]["routing"] == {"evidence_retriever": 1}
    assert "extraction_failure" in body["alerts"]
    # 1 failed of 7 (~14%) is below the 20% default threshold -> not firing
    assert body["alerts"]["extraction_failure"]["firing"] is False
    assert body["window"]["events"] == len(buf.snapshot())
    assert body["window"]["buffer_max"] == 100


def test_metrics_extraction_alert_fires_on_high_failure_rate():
    # 1 ok + 5 unsupported of 6 (~83%) over the 5-field floor -> firing
    buf = _populate(EventBuffer(maxlen=100), ok=1, unsupported=5)
    server = _serve(_handler_with(buf))
    try:
        status, body = _get(server.server_address[1], "/metrics")
    finally:
        server.shutdown()

    assert status == 200
    assert body["alerts"]["extraction_failure"]["firing"] is True


def test_metrics_empty_buffer_is_zeros_and_not_firing():
    server = _serve(_handler_with(EventBuffer(maxlen=10)))
    try:
        status, body = _get(server.server_address[1], "/metrics")
    finally:
        server.shutdown()

    assert status == 200
    assert body["panels"]["ingestion_count"] == 0
    assert body["panels"]["extraction"]["field_pass_rate"] == 0.0
    assert body["panels"]["retrieval"]["hit_rate"] == 0.0
    assert body["alerts"]["extraction_failure"]["firing"] is False
    assert body["window"]["events"] == 0


def test_metrics_requires_no_auth():
    # No Authorization header — must still return 200 like /ready.
    server = _serve(_handler_with(EventBuffer(maxlen=10)))
    try:
        status, _ = _get(server.server_address[1], "/metrics")
    finally:
        server.shutdown()
    assert status == 200
