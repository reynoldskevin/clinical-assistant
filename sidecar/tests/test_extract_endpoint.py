"""Tests for the sidecar's POST /extract endpoint (auto-extract on upload).

``process_extract`` is exercised directly with a fake extract-fn (no sockets, no
live VLM, no running OpenEMR), mirroring test_server.py. Verifies auth
enforcement, input validation, JWT/pid/document_id/doc_type forwarding, the
success envelope, and that internal failures never leak — a schema-invalid
extraction surfaces as 422 ("couldn't extract"), any other failure as a generic
502. ``default_extract_builder`` is tested with fakes to prove it wires the
pid-scoped boundary + VLM into ``attach_and_extract`` and serializes the fact.
"""
import json

import pytest
from pydantic import ValidationError

from contracts import LabFact
from server import default_extract_builder, process_extract


def _ok_fn(record=None):
    """A fake extract-fn returning a fixed envelope and recording its args."""
    def extract(pid, jwt, document_id, doc_type):
        if record is not None:
            record.update(pid=pid, jwt=jwt, document_id=document_id, doc_type=doc_type)
        return {
            "ok": True,
            "doc_type": doc_type,
            "confidence": 0.95,
            "unsupported_fields": [],
            "fact": {"test_name": "HbA1c", "value": "7.8"},
            "correlation_id": "cid-xyz",
        }

    return extract


def _body(**kw):
    return json.dumps(kw).encode()


def test_valid_request_returns_fact_and_forwards_all_fields():
    record = {}
    status, out = process_extract(
        "Bearer tok-123",
        _body(pid=3, document_id=42, doc_type="lab_pdf"),
        _ok_fn(record),
    )
    assert status == 200
    assert out["ok"] is True
    assert out["doc_type"] == "lab_pdf"
    assert out["fact"] == {"test_name": "HbA1c", "value": "7.8"}
    # The forwarded credential, fixed pid, document id, and doc_type reach the fn.
    assert record == {"pid": 3, "jwt": "tok-123", "document_id": 42, "doc_type": "lab_pdf"}


def test_missing_bearer_is_unauthorized():
    status, out = process_extract("", _body(pid=3, document_id=1, doc_type="lab_pdf"), _ok_fn())
    assert status == 401
    assert "error" in out


def test_empty_bearer_is_unauthorized():
    status, _ = process_extract("Bearer   ", _body(pid=3, document_id=1, doc_type="lab_pdf"), _ok_fn())
    assert status == 401


def test_invalid_json_is_bad_request():
    status, _ = process_extract("Bearer t", b"not json", _ok_fn())
    assert status == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"pid": 0, "document_id": 1, "doc_type": "lab_pdf"},      # no patient
        {"pid": 3, "document_id": 0, "doc_type": "lab_pdf"},      # no document
        {"pid": 3, "document_id": 1, "doc_type": "bogus"},        # unknown doc_type
        {"pid": 3, "document_id": 1},                             # missing doc_type
    ],
)
def test_missing_or_invalid_fields_are_bad_request(payload):
    status, out = process_extract("Bearer t", _body(**payload), _ok_fn())
    assert status == 400
    assert "error" in out


def test_schema_invalid_extraction_is_422_without_detail():
    """A contract ValidationError (VLM omitted/invented a field) → 422, no leak."""
    def bad(pid, jwt, document_id, doc_type):
        LabFact.model_validate({"test_name": "HbA1c"})  # missing required fields → raises
        return {}  # unreachable

    status, out = process_extract("Bearer t", _body(pid=3, document_id=1, doc_type="lab_pdf"), bad)
    assert status == 422
    assert out == {"error": "could not extract a valid fact from this document"}


def test_extractor_outage_is_generic_502():
    def boom(pid, jwt, document_id, doc_type):
        raise RuntimeError("read.php 500 / anthropic timeout")

    status, out = process_extract("Bearer t", _body(pid=3, document_id=1, doc_type="lab_pdf"), boom)
    assert status == 502
    assert out == {"error": "document extraction is unavailable"}
    # The internal message never crosses to the caller.
    assert "read.php" not in json.dumps(out)


# --- default_extract_builder wiring ------------------------------------------


class _FakeBoundary:
    """Stub chart boundary: returns fixed document bytes for get_document."""

    def __init__(self):
        self.calls = []

    def get_document(self, pid, document_id):
        self.calls.append((pid, document_id))
        return {"mimetype": "application/pdf", "document_data": "ZmFrZQ=="}


class _FakeText:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeText(text)]


def test_default_extract_builder_wires_boundary_and_vlm(monkeypatch):
    import server as server_module

    captured = {}
    fake_boundary = _FakeBoundary()

    def fake_build_chart_boundary(url, jwt, *, correlation_id=None):
        captured["url"] = url
        captured["jwt"] = jwt
        return fake_boundary

    # The VLM returns a well-formed envelope for a LabFact.
    envelope = {
        "confidence": 0.9,
        "unsupported_fields": [],
        "fact": {
            "test_name": "HbA1c",
            "value": "7.8",
            "unit": "%",
            "reference_range": "4.0-5.6",
            "collection_date": "2026-01-02",
            "abnormal_flag": "high",
            "source_citation": "Result line 1",
        },
    }

    def fake_message_creator(**kwargs):
        captured["vlm_called"] = True
        return _FakeMessage(json.dumps(envelope))

    monkeypatch.setattr(server_module, "build_chart_boundary", fake_build_chart_boundary)

    extract = default_extract_builder(
        "http://openemr/summary.php", fake_message_creator, "http://openemr/read.php"
    )
    out = extract(7, "tok-abc", 99, "lab_pdf")

    # Boundary was built with the read URL + forwarded JWT and read the doc pid-scoped.
    assert captured["url"] == "http://openemr/read.php"
    assert captured["jwt"] == "tok-abc"
    assert fake_boundary.calls == [(7, 99)]
    assert captured.get("vlm_called") is True

    # The validated fact is serialized back; a correlation id is always present.
    assert out["ok"] is True
    assert out["doc_type"] == "lab_pdf"
    assert out["confidence"] == 0.9
    assert out["fact"]["test_name"] == "HbA1c"
    assert out["correlation_id"]
