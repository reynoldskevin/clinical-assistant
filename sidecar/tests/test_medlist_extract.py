"""T75a acceptance tests (LOCKED) — med_list (third document type) extraction.

A medication-list PDF is the third document type, mirroring lab_pdf/intake_form:
the VLM returns a STRICT `MedicationListFact` (a flat human-readable `medications`
string — no nested objects/arrays — plus a mandatory non-empty `source_citation`),
`med_list` is an accepted `doc_type` everywhere (server `_DOC_TYPES`, the
`ExtractRequest` enum, and — via the locked T60 parity guard — the OpenAPI spec),
and the /extract envelope carries NO identity_check (that stays intake-only).

Unit tests only: the VLM message-creator and the chart boundary are injected
fakes — no anthropic SDK, no network, no running OpenEMR.
"""
import base64
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from contracts import ExtractRequest, MedicationListFact
from extractor import attach_and_extract
from server import default_extract_builder


# --- fakes (mirror test_extractor.py) ----------------------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _resp(text):
    return SimpleNamespace(content=[_text(text)], stop_reason="end_turn")


class ScriptedVlm:
    def __init__(self, envelope):
        self._body = json.dumps(envelope) if not isinstance(envelope, str) else envelope
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _resp(self._body)


class FakeBoundary:
    def __init__(self, doc):
        self._doc = doc

    def get_document(self, pid, document_id):
        return self._doc


_MED_DOC = {
    "id": 601,
    "mimetype": "application/pdf",
    "doc_type": "med_list",
    "document_data": base64.b64encode(b"%PDF-1.4 synthetic medication list").decode("ascii"),
}


def _med_fact(**over):
    fact = {
        "medications": "Lisinopril 10 mg PO once daily; Metformin 500 mg PO twice daily",
        "source_citation": "Medication list, page 1",
    }
    fact.update(over)
    return fact


def _med_envelope(**over):
    return {"confidence": 0.95, "unsupported_fields": [], "fact": _med_fact(**over)}


# --- doc_type is accepted everywhere -----------------------------------------

def test_med_list_is_an_accepted_server_doc_type():
    import server
    assert "med_list" in server._DOC_TYPES


def test_med_list_is_in_the_extract_request_enum():
    enum = ExtractRequest.model_json_schema()["properties"]["doc_type"].get("enum") or []
    assert "med_list" in enum
    # a med_list request validates against the contract
    ExtractRequest.model_validate({"pid": 1, "document_id": 601, "doc_type": "med_list"})


# --- MedicationListFact strict schema ----------------------------------------

def test_medicationlistfact_requires_all_named_fields():
    for missing in ("medications", "source_citation"):
        fact = _med_fact()
        del fact[missing]
        with pytest.raises(ValidationError):
            MedicationListFact.model_validate(fact)


def test_medicationlistfact_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        MedicationListFact.model_validate(_med_fact(surprise="x"))


def test_medicationlistfact_requires_non_empty_source_citation():
    with pytest.raises(ValidationError):
        MedicationListFact.model_validate(_med_fact(source_citation=""))


def test_medicationlistfact_allows_null_medications():
    # groundable-but-absent -> explicit null (surfaced via unsupported_fields), the
    # key is still required to be present.
    fact = MedicationListFact.model_validate(_med_fact(medications=None))
    assert fact.medications is None
    assert fact.source_citation


def test_medications_is_a_flat_string_not_nested():
    # the contract forbids nested objects/arrays inside the fact (VLM must combine
    # into one human-readable string)
    with pytest.raises(ValidationError):
        MedicationListFact.model_validate(_med_fact(medications=[{"drug": "X"}]))


# --- extractor round-trip ----------------------------------------------------

def test_attach_and_extract_returns_a_medicationlistfact():
    vlm = ScriptedVlm(_med_envelope())
    result = attach_and_extract(1, 601, "med_list", chart_boundary=FakeBoundary(_MED_DOC), message_creator=vlm)

    assert isinstance(result.fact, MedicationListFact)
    assert result.fact.medications.startswith("Lisinopril")
    assert result.fact.source_citation
    assert result.doc_type == "med_list"
    assert 0.0 <= result.confidence <= 1.0
    assert result.unsupported_fields == []


def test_attach_and_extract_flags_unsupported_medications():
    vlm = ScriptedVlm({"confidence": 0.5, "unsupported_fields": ["medications"], "fact": _med_fact(medications=None)})
    result = attach_and_extract(1, 601, "med_list", chart_boundary=FakeBoundary(_MED_DOC), message_creator=vlm)
    assert "medications" in result.unsupported_fields
    assert result.fact.medications is None


# --- /extract envelope: no identity_check for med_list -----------------------

def _wire_extract(monkeypatch, envelope):
    import server as server_module

    class _FakeChart:
        def get_document(self, pid, document_id):
            return {"mimetype": "application/pdf", "document_data": "ZmFrZQ=="}

    monkeypatch.setattr(
        server_module, "build_chart_boundary",
        lambda url, jwt, *, correlation_id=None: _FakeChart(),
    )

    def fake_message_creator(**kwargs):
        return _resp(json.dumps(envelope))

    return default_extract_builder("http://oe/summary.php", fake_message_creator, "http://oe/read.php")


def test_med_list_extract_envelope_has_no_identity_check(monkeypatch):
    extract = _wire_extract(monkeypatch, _med_envelope())
    out = extract(3, "tok", 601, "med_list")

    assert out["ok"] is True
    assert out["doc_type"] == "med_list"
    assert "identity_check" not in out          # identity check is intake-only
    assert out["fact"]["medications"].startswith("Lisinopril")
    assert out["correlation_id"]
    json.dumps(out)                              # JSON-serializable
