"""T50 acceptance tests (LOCKED) — citation gate.

Pins the machine-readable 5-field citation contract, the demotion of any
clinical claim that carries no citation, and the separation of patient-record
facts from guideline evidence into distinct sections/markers.

Pure and deterministic — no anthropic SDK, no live API call. The Week 1
verification gate (``test_verification*.py``) is the regression guard and must
stay green alongside these; this module composes with it, it does not replace it.
"""
import pytest
from pydantic import ValidationError

from citation_gate import (
    Citation,
    CitationGate,
    DEMOTION_NOTE,
    GUIDELINE_SECTION_HEADER,
    RECORD_SECTION_HEADER,
    SOURCE_GUIDELINE,
    SOURCE_RECORD,
)


def _record_citation(**over):
    """A valid patient-record citation dict; override individual fields via kwargs."""
    base = {
        "source_type": SOURCE_RECORD,
        "source_id": "prescription:1",
        "page_or_section": "Medications",
        "field_or_chunk_id": "drug",
        "quote_or_value": "Warfarin 5 mg",
    }
    base.update(over)
    return base


def _guideline_citation(**over):
    base = {
        "source_type": SOURCE_GUIDELINE,
        "source_id": "afib_anticoagulation:target-inr",
        "page_or_section": "Anticoagulation",
        "field_or_chunk_id": "afib_anticoagulation:target-inr",
        "quote_or_value": "target INR 2.0-3.0",
    }
    base.update(over)
    return base


# --- citation contract shape --------------------------------------------------

def test_citation_contract_has_exactly_the_five_fields():
    c = Citation(**_record_citation())
    assert c.source_type == SOURCE_RECORD
    assert c.source_id == "prescription:1"
    assert c.page_or_section == "Medications"
    assert c.field_or_chunk_id == "drug"
    assert c.quote_or_value == "Warfarin 5 mg"
    assert set(Citation.model_fields) == {
        "source_type",
        "source_id",
        "page_or_section",
        "field_or_chunk_id",
        "quote_or_value",
    }


def test_citation_rejects_a_missing_field():
    incomplete = _record_citation()
    del incomplete["quote_or_value"]
    with pytest.raises(ValidationError):
        Citation(**incomplete)


def test_citation_rejects_an_unknown_field():
    with pytest.raises(ValidationError):
        Citation(**_record_citation(smuggled="nope"))


def test_citation_rejects_an_empty_required_value():
    with pytest.raises(ValidationError):
        Citation(**_record_citation(source_id=""))


# --- gate verdict schema ------------------------------------------------------

def test_gate_verdict_has_the_documented_schema():
    result = CitationGate().gate([])
    assert set(result.keys()) >= {
        "verdict",
        "flags",
        "record_facts",
        "guideline_evidence",
        "rendered_answer",
    }
    assert result["verdict"] in {"pass", "pass_with_flags", "blocked"}
    assert result["verdict"] == "pass"
    assert result["flags"] == []


# --- every clinical claim must carry a citation -------------------------------

def test_fully_cited_answer_passes_clean():
    result = CitationGate().gate(
        [
            {"text": "On Warfarin 5 mg.", "citation": _record_citation()},
            {"text": "Target INR is 2-3 for AFib.", "citation": _guideline_citation()},
        ]
    )
    assert result["verdict"] == "pass"
    assert result["flags"] == []


def test_gate_accepts_a_citation_instance_not_only_a_dict():
    result = CitationGate().gate(
        [{"text": "On Warfarin 5 mg.", "citation": Citation(**_record_citation())}]
    )
    assert result["verdict"] == "pass"
    assert any("Warfarin" in fact for fact in result["record_facts"])


def test_uncited_clinical_claim_is_demoted_and_flagged():
    result = CitationGate().gate(
        [
            {"text": "On Warfarin 5 mg.", "citation": _record_citation()},
            {"text": "The glucose was 180 mg/dL.", "citation": None},
        ]
    )
    # A missing citation is not silently accepted: the answer no longer passes clean.
    assert result["verdict"] in {"pass_with_flags", "blocked"}
    assert any(f["code"] == "uncited_claim" for f in result["flags"])
    # The uncited claim is NOT presented as a clean grounded record fact...
    assert not any("180" in fact for fact in result["record_facts"])
    assert not any("180" in ev for ev in result["guideline_evidence"])
    # ...and where it does surface it is demoted (marked), never as fact.
    assert DEMOTION_NOTE in result["rendered_answer"]


def test_gate_rejects_a_malformed_citation():
    # A structurally-invalid citation is a contract violation, not "uncited".
    with pytest.raises(ValidationError):
        CitationGate().gate(
            [{"text": "x", "citation": {"source_type": SOURCE_RECORD}}]
        )


# --- record facts vs guideline evidence separation ----------------------------

def test_record_and_guideline_facts_are_separated_into_distinct_sections():
    result = CitationGate().gate(
        [
            {"text": "On Warfarin 5 mg.", "citation": _record_citation()},
            {"text": "Guideline target INR is 2-3.", "citation": _guideline_citation()},
        ]
    )
    # distinct destination buckets
    assert any("Warfarin" in fact for fact in result["record_facts"])
    assert not any("Warfarin" in ev for ev in result["guideline_evidence"])
    assert any("INR" in ev for ev in result["guideline_evidence"])
    assert not any("INR" in fact for fact in result["record_facts"])

    # distinct section markers in the rendered answer
    assert RECORD_SECTION_HEADER != GUIDELINE_SECTION_HEADER
    rendered = result["rendered_answer"]
    assert RECORD_SECTION_HEADER in rendered
    assert GUIDELINE_SECTION_HEADER in rendered
    # record facts are presented before guideline evidence (stable ordering)
    assert rendered.index(RECORD_SECTION_HEADER) < rendered.index(GUIDELINE_SECTION_HEADER)
    # each claim's text lands under its own section
    assert "Warfarin" in rendered
    assert "INR" in rendered
