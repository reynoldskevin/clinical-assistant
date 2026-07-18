"""Focused validation tests for the lab_pdf / intake_form extraction schemas.

These pin the Week-2 document-extraction contracts (``LabFact`` for ``lab_pdf``,
``IntakeFact`` for ``intake_form``) as the single source of truth, with special
attention to the **source-citation field**: grounding is mandatory, so
``source_citation`` is a required, non-null, non-empty string on every extracted
fact, and that requirement is visible in the JSON schema the tool advertises.

Everything here is pure pydantic — no LLM, no network, no I/O, no keys.
"""
import pytest
from pydantic import ValidationError

from contracts import IntakeFact, LabFact

# --- fully-grounded exemplars (every field present; citation non-empty) --------

_LAB_OK = {
    "test_name": "HbA1c",
    "value": "8.1",
    "unit": "%",
    "reference_range": "4.0-5.6",
    "collection_date": "2026-05-01",
    "abnormal_flag": "H",
    "source_citation": "p.2, results table, row 3",
}

_INTAKE_OK = {
    "demographics": "Jordan A. Rivera; DOB 1968-03-04; Female",
    "chief_concern": "follow-up on blood sugar",
    "current_medications": "metformin 500mg BID",
    "allergies": "penicillin",
    "family_history": "father: type 2 diabetes",
    "source_citation": "intake form, section 1",
}


# --- happy path: a fully-grounded fact validates -------------------------------

def test_lab_fact_accepts_a_fully_grounded_result():
    fact = LabFact.model_validate(_LAB_OK)
    assert fact.source_citation == "p.2, results table, row 3"
    assert fact.value == "8.1"


def test_intake_fact_accepts_a_fully_grounded_form():
    fact = IntakeFact.model_validate(_INTAKE_OK)
    assert fact.source_citation == "intake form, section 1"
    assert fact.chief_concern == "follow-up on blood sugar"


# --- source_citation is MANDATORY (grounding is not optional) ------------------

@pytest.mark.parametrize("model, ok", [(LabFact, _LAB_OK), (IntakeFact, _INTAKE_OK)])
def test_missing_source_citation_is_rejected(model, ok):
    data = dict(ok)
    del data["source_citation"]
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model, ok", [(LabFact, _LAB_OK), (IntakeFact, _INTAKE_OK)])
def test_null_source_citation_is_rejected(model, ok):
    with pytest.raises(ValidationError):
        model.model_validate({**ok, "source_citation": None})


@pytest.mark.parametrize("model, ok", [(LabFact, _LAB_OK), (IntakeFact, _INTAKE_OK)])
def test_empty_source_citation_is_rejected(model, ok):
    # min_length=1 — an empty grounding string is a contract violation.
    with pytest.raises(ValidationError):
        model.model_validate({**ok, "source_citation": ""})


# --- groundable-but-absent field → null is allowed (never invented) ------------

def test_lab_fact_allows_null_for_an_ungroundable_field():
    # A field the VLM could not ground is explicitly null (and surfaced via
    # unsupported_fields downstream), NOT invented — but the citation still holds.
    fact = LabFact.model_validate({**_LAB_OK, "abnormal_flag": None})
    assert fact.abnormal_flag is None
    assert fact.source_citation  # grounding intact


def test_intake_fact_allows_null_for_an_ungroundable_field():
    fact = IntakeFact.model_validate({**_INTAKE_OK, "family_history": None})
    assert fact.family_history is None
    assert fact.source_citation


# --- every named field is a REQUIRED key (must be present, may be null) --------

@pytest.mark.parametrize("model, ok", [(LabFact, _LAB_OK), (IntakeFact, _INTAKE_OK)])
def test_every_named_field_is_a_required_key(model, ok):
    for field in ok:
        data = {k: v for k, v in ok.items() if k != field}
        with pytest.raises(ValidationError):
            model.model_validate(data)


# --- strict: unknown fields are rejected (the VLM cannot smuggle extras) --------

@pytest.mark.parametrize("model, ok", [(LabFact, _LAB_OK), (IntakeFact, _INTAKE_OK)])
def test_unknown_fields_are_rejected(model, ok):
    with pytest.raises(ValidationError):
        model.model_validate({**ok, "surprise_field": "x"})


# --- the JSON schema advertises the citation requirement -----------------------

@pytest.mark.parametrize("model", [LabFact, IntakeFact])
def test_json_schema_marks_source_citation_required_and_non_empty(model):
    schema = model.model_json_schema()
    assert "source_citation" in schema["required"]
    assert schema["properties"]["source_citation"].get("minLength") == 1
    # extra="forbid" surfaces as additionalProperties: false
    assert schema.get("additionalProperties") is False
