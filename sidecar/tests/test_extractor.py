"""T47 acceptance tests (LOCKED) — VLM document extractor.

Claude vision reads a document that was stored by the T46 upload path and fetched
back through the pid-scoped read boundary (get_document → base64 content), and
returns a STRICT LabFact / IntakeFact. The Pydantic schema is the source of truth:
raw VLM output is validated before any downstream use and never bypasses the
contract. Unsupported / low-confidence fields are flagged, never invented.

Unit tests only: the Claude message-creator (VLM) and the chart boundary are
injected fakes — no anthropic SDK import, no live API call, no running OpenEMR.
The VLM returns an envelope ``{confidence, unsupported_fields, fact}`` in a text
block, mirroring the SDK Message shape (.content blocks).
"""
import base64
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from contracts import IntakeFact, LabFact
from extractor import attach_and_extract


# --- fakes -------------------------------------------------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _resp(text):
    return SimpleNamespace(content=[_text(text)], stop_reason="end_turn")


class ScriptedVlm:
    """A fake message-creator returning one scripted response, recording calls."""

    def __init__(self, envelope):
        self._body = json.dumps(envelope) if not isinstance(envelope, str) else envelope
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _resp(self._body)


class FakeBoundary:
    """A fake chart boundary whose get_document returns one stored document."""

    def __init__(self, doc):
        self._doc = doc
        self.calls = []

    def get_document(self, pid, document_id):
        self.calls.append((pid, document_id))
        return self._doc


_LAB_BYTES = b"%PDF-1.4 synthetic lab report"
_LAB_DOC = {
    "id": 501,
    "mimetype": "application/pdf",
    "doc_type": "lab_pdf",
    "document_data": base64.b64encode(_LAB_BYTES).decode("ascii"),
}
_INTAKE_DOC = {
    "id": 502,
    "mimetype": "image/png",
    "doc_type": "intake_form",
    "document_data": base64.b64encode(b"intake png bytes").decode("ascii"),
}


def _lab_fact(**over):
    fact = {
        "test_name": "Hemoglobin A1c",
        "value": "7.2",
        "unit": "%",
        "reference_range": "4.0-5.6",
        "collection_date": "2021-03-20",
        "abnormal_flag": "H",
        "source_citation": "page 1, results table row 3",
    }
    fact.update(over)
    return fact


def _intake_fact(**over):
    fact = {
        "demographics": "F, 54, DOB 1967-02-11",
        "chief_concern": "follow-up for elevated blood sugar",
        "current_medications": "metformin 500mg BID",
        "allergies": "penicillin",
        "family_history": "father — type 2 diabetes",
        "source_citation": "intake form, section 2",
    }
    fact.update(over)
    return fact


# --- happy path --------------------------------------------------------------

def test_extracts_valid_labfact_from_clean_pdf():
    vlm = ScriptedVlm({"confidence": 0.96, "unsupported_fields": [], "fact": _lab_fact()})
    result = attach_and_extract(1, 501, "lab_pdf", chart_boundary=FakeBoundary(_LAB_DOC), message_creator=vlm)

    assert isinstance(result.fact, LabFact)
    assert result.fact.test_name == "Hemoglobin A1c"
    assert result.fact.value == "7.2"
    assert result.fact.source_citation
    assert 0.0 <= result.confidence <= 1.0
    assert result.unsupported_fields == []


def test_extracts_valid_intakefact_from_clean_form():
    vlm = ScriptedVlm({"confidence": 0.9, "unsupported_fields": [], "fact": _intake_fact()})
    result = attach_and_extract(1, 502, "intake_form", chart_boundary=FakeBoundary(_INTAKE_DOC), message_creator=vlm)

    assert isinstance(result.fact, IntakeFact)
    assert result.fact.chief_concern.startswith("follow-up")
    assert result.fact.source_citation


def test_document_is_fetched_via_boundary_and_its_bytes_sent_to_the_vlm():
    boundary = FakeBoundary(_LAB_DOC)
    vlm = ScriptedVlm({"confidence": 0.95, "unsupported_fields": [], "fact": _lab_fact()})

    attach_and_extract(7, 501, "lab_pdf", chart_boundary=boundary, message_creator=vlm)

    # the stored document was fetched pid-scoped through the boundary
    assert boundary.calls == [(7, 501)]
    # and its base64 content reached the VLM call payload
    payload = json.dumps(vlm.calls[0].get("messages"))
    assert _LAB_DOC["document_data"] in payload


# --- schema is the source of truth (no bypass, no invention) -----------------

def test_missing_required_field_raises():
    # the VLM omits `value` — a required LabFact field. Validation must reject it
    # rather than pass a partial fact downstream.
    fact = _lab_fact()
    del fact["value"]
    vlm = ScriptedVlm({"confidence": 0.8, "unsupported_fields": [], "fact": fact})
    with pytest.raises(ValidationError):
        attach_and_extract(1, 501, "lab_pdf", chart_boundary=FakeBoundary(_LAB_DOC), message_creator=vlm)


def test_hallucinated_extra_field_is_rejected():
    # the VLM invents a field not in the schema — the strict contract must reject
    # it (schema is the source of truth; the model cannot smuggle unknown fields).
    vlm = ScriptedVlm(
        {"confidence": 0.8, "unsupported_fields": [], "fact": _lab_fact(made_up_code="Z99.9")}
    )
    with pytest.raises(ValidationError):
        attach_and_extract(1, 501, "lab_pdf", chart_boundary=FakeBoundary(_LAB_DOC), message_creator=vlm)


def test_unsupported_field_is_flagged_not_invented():
    # the VLM could not ground `unit`: it returns null and flags it. The extractor
    # must surface the flag and leave the value null — never fabricate a plausible
    # unit.
    vlm = ScriptedVlm(
        {"confidence": 0.55, "unsupported_fields": ["unit"], "fact": _lab_fact(unit=None)}
    )
    result = attach_and_extract(1, 501, "lab_pdf", chart_boundary=FakeBoundary(_LAB_DOC), message_creator=vlm)

    assert "unit" in result.unsupported_fields
    assert result.fact.unit is None


# --- confidence recorded, PHI-free -------------------------------------------

def test_confidence_telemetry_is_phi_free():
    vlm = ScriptedVlm({"confidence": 0.72, "unsupported_fields": ["abnormal_flag"], "fact": _lab_fact(abnormal_flag=None)})
    result = attach_and_extract(1, 501, "lab_pdf", chart_boundary=FakeBoundary(_LAB_DOC), message_creator=vlm)

    tele = result.telemetry()
    assert tele["confidence"] == pytest.approx(0.72)
    assert tele["doc_type"] == "lab_pdf"
    # telemetry is safe to log: it carries NONE of the extracted PHI values.
    blob = json.dumps(tele)
    for phi in ("Hemoglobin", "7.2", "2021-03-20", base64.b64encode(_LAB_BYTES).decode("ascii")):
        assert phi not in blob


# --- contracts ---------------------------------------------------------------

def test_labfact_requires_all_named_fields():
    for missing in ("test_name", "value", "unit", "reference_range", "collection_date", "abnormal_flag", "source_citation"):
        fact = _lab_fact()
        del fact[missing]
        with pytest.raises(ValidationError):
            LabFact.model_validate(fact)


def test_intakefact_requires_all_named_fields():
    for missing in ("demographics", "chief_concern", "current_medications", "allergies", "family_history", "source_citation"):
        fact = _intake_fact()
        del fact[missing]
        with pytest.raises(ValidationError):
            IntakeFact.model_validate(fact)


def test_facts_reject_unknown_fields():
    with pytest.raises(ValidationError):
        LabFact.model_validate(_lab_fact(surprise="x"))
    with pytest.raises(ValidationError):
        IntakeFact.model_validate(_intake_fact(surprise="x"))
