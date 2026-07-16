"""T68 acceptance tests (LOCKED) — extract-time wrong-chart wiring.

Proves `server.default_extract_builder` runs the deterministic identity check on
the extract path for an intake form and surfaces an `identity_check` block in the
`/extract` response, so the "Possible wrong-chart / wrong-patient upload" banner
appears the moment the form is extracted — before any question is asked.

Offline: the VLM message-creator, the chart (get_document) boundary, and the
summary (demographics) boundary are injected fakes — no anthropic SDK, no
network, no running OpenEMR.
"""
import json

import pytest

from server import default_extract_builder, process_extract


# The seeded chart the summary boundary returns.
CHART_DEMOGRAPHICS = {
    "pid": 1,
    "fname": "Brett333",
    "lname": "Cruickshank494",
    "dob": "1925-06-24",
    "sex": "Female",
}


class _FakeChartBoundary:
    """Stub chart boundary: fixed intake image bytes for get_document."""

    def get_document(self, pid, document_id):
        return {"mimetype": "image/png", "document_data": "ZmFrZQ=="}


class _FakeText:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeText(text)]


def _intake_envelope(demographics: str) -> dict:
    return {
        "confidence": 0.95,
        "unsupported_fields": [],
        "fact": {
            "demographics": demographics,
            "chief_concern": "follow-up",
            "current_medications": "metformin 500mg",
            "allergies": "penicillin",
            "family_history": "father — diabetes",
            "source_citation": "intake form, section 1",
        },
    }


def _lab_envelope() -> dict:
    return {
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


def _wire(monkeypatch, envelope, *, summary=CHART_DEMOGRAPHICS, summary_raises=False):
    """Patch both boundaries + the VLM and return the built extract fn."""
    import server as server_module

    monkeypatch.setattr(
        server_module, "build_chart_boundary",
        lambda url, jwt, *, correlation_id=None: _FakeChartBoundary(),
    )

    def fake_build_boundary(url, jwt, *, correlation_id=None):
        def boundary(pid):
            if summary_raises:
                raise RuntimeError("summary.php 502")
            return {"demographics": dict(summary)}
        return boundary

    monkeypatch.setattr(server_module, "build_boundary", fake_build_boundary)

    def fake_message_creator(**kwargs):
        return _FakeMessage(json.dumps(envelope))

    return default_extract_builder(
        "http://openemr/summary.php", fake_message_creator, "http://openemr/read.php"
    )


# --- intake form: mismatch surfaces the warning ------------------------------

def test_intake_mismatch_surfaces_identity_check_warning(monkeypatch):
    extract = _wire(monkeypatch, _intake_envelope("Jordan A. Rivera; DOB 1988-03-02; Male"))
    out = extract(1, "tok", 55, "intake_form")

    assert out["ok"] is True
    assert "identity_check" in out
    ic = out["identity_check"]
    assert ic["matches"] is False
    assert ic["warning"] == "possible_wrong_chart"
    assert set(ic["mismatched_identifiers"]) == {"name", "DOB", "sex"}
    # The extracted fact is still returned alongside the warning.
    assert out["fact"]["demographics"] == "Jordan A. Rivera; DOB 1988-03-02; Male"
    # Response is JSON-serializable.
    json.dumps(out)


def test_intake_match_reports_a_clean_identity_check(monkeypatch):
    extract = _wire(monkeypatch, _intake_envelope("Brett333 Cruickshank494; DOB 1925-06-24; Female"))
    out = extract(1, "tok", 55, "intake_form")

    assert "identity_check" in out
    assert out["identity_check"]["matches"] is True
    assert out["identity_check"]["mismatched_identifiers"] == []
    assert out["identity_check"].get("warning") in (None, "")


# --- scope + fail-open --------------------------------------------------------

def test_lab_pdf_extraction_has_no_identity_check(monkeypatch):
    extract = _wire(monkeypatch, _lab_envelope())
    out = extract(3, "tok", 42, "lab_pdf")
    assert out["ok"] is True
    assert "identity_check" not in out


def test_summary_boundary_outage_is_fail_open(monkeypatch):
    # If the chart demographics cannot be fetched, extraction still succeeds and
    # simply omits the identity check — a verification outage never blocks the
    # extracted fact, and we never cry wolf on an unverifiable upload.
    extract = _wire(
        monkeypatch,
        _intake_envelope("Jordan A. Rivera; DOB 1988-03-02; Male"),
        summary_raises=True,
    )
    # process_extract wraps the fn; a fail-open check must NOT turn into a 502.
    status, out = process_extract(
        "Bearer tok",
        json.dumps({"pid": 1, "document_id": 55, "doc_type": "intake_form"}).encode(),
        lambda pid, jwt, document_id, doc_type: extract(pid, jwt, document_id, doc_type),
    )
    assert status == 200
    assert out["ok"] is True
    assert out["fact"]["demographics"] == "Jordan A. Rivera; DOB 1988-03-02; Male"
    assert "identity_check" not in out
