"""Over-the-socket routing tests for POST /extract.

Boots the real ``make_handler`` on a loopback ephemeral port and drives it with
``http.client`` to prove the route is wired into ``do_POST`` (not just that the
pure ``process_extract`` works): a bearer request reaches the injected
extract-fn and returns the fact; a missing bearer is 401; and when the endpoint
is not enabled (``extract_fn=None``) the path 404s like any unknown route.
"""
import http.client
import json
import threading

from http.server import ThreadingHTTPServer

from server import make_handler


def _agent_builder(pid, jwt):  # unused by /extract, required by make_handler
    raise AssertionError("agent builder must not be called for /extract")


def _serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _post(port, path, body, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", path, body=json.dumps(body), headers=headers or {})
        res = conn.getresponse()
        return res.status, json.loads(res.read() or b"{}")
    finally:
        conn.close()


def test_extract_route_reaches_the_injected_fn():
    record = {}

    def extract_fn(pid, jwt, document_id, doc_type):
        record.update(pid=pid, jwt=jwt, document_id=document_id, doc_type=doc_type)
        return {"ok": True, "doc_type": doc_type, "confidence": 0.9,
                "unsupported_fields": [], "fact": {"test_name": "HbA1c"}}

    handler = make_handler(_agent_builder, "*", None, None, extract_fn)
    server = _serve(handler)
    try:
        status, body = _post(
            server.server_address[1],
            "/extract",
            {"pid": 5, "document_id": 12, "doc_type": "lab_pdf"},
            {"Authorization": "Bearer tok-9", "Content-Type": "application/json"},
        )
    finally:
        server.shutdown()

    assert status == 200
    assert body["fact"] == {"test_name": "HbA1c"}
    assert record == {"pid": 5, "jwt": "tok-9", "document_id": 12, "doc_type": "lab_pdf"}


def test_extract_route_requires_bearer():
    handler = make_handler(_agent_builder, "*", None, None, lambda *a: {"ok": True})
    server = _serve(handler)
    try:
        status, body = _post(
            server.server_address[1],
            "/extract",
            {"pid": 5, "document_id": 12, "doc_type": "lab_pdf"},
            {"Content-Type": "application/json"},
        )
    finally:
        server.shutdown()

    assert status == 401
    assert "error" in body


def test_extract_route_404s_when_disabled():
    # No extract_fn -> the endpoint is not mounted; the path is unknown.
    handler = make_handler(_agent_builder, "*", None, None, None)
    server = _serve(handler)
    try:
        status, _ = _post(
            server.server_address[1],
            "/extract",
            {"pid": 5, "document_id": 12, "doc_type": "lab_pdf"},
            {"Authorization": "Bearer tok-9", "Content-Type": "application/json"},
        )
    finally:
        server.shutdown()

    assert status == 404
