"""T37 acceptance tests (LOCKED) — canonical Pydantic contracts for every tool.

The contracts are the source of truth: each tool's advertised input_schema is
DERIVED from its Pydantic input model, handlers parse input through the input
model, and handlers validate output through the output model (known fields typed;
unknown fields ignored so a new PHP field never breaks a turn; original data
returned unchanged). Deterministic — no anthropic SDK, no sockets, no live API.
"""
import os

import pytest
from pydantic import ValidationError

import contracts
from agent import ClaudeAgent
from contracts import (
    EmptyToolInput,
    EncounterRow,
    GetEncounterInput,
    GetMedicationsInput,
    LabResult,
    MedicationRow,
    NoteSnippet,
    PatientSummary,
    SearchChartInput,
)
from factory import (
    build_encounter_tools,
    build_medications_tool,
    build_results_tool,
    build_search_tool,
)


# --- a minimal chart-boundary fake -------------------------------------------

class FakeBoundary:
    def __init__(self, rows):
        self._rows = rows

    def list_encounters(self, pid):
        return self._rows

    def get_encounter(self, pid, encounter_id):
        return {"ref": f"encounter:{encounter_id}"}

    def get_results(self, pid):
        return self._rows

    def get_medications(self, pid, active_only=False):
        return self._rows

    def search_chart(self, pid, query, limit=20):
        return self._rows


def _tool_by_name(specs, name):
    return next(s for s in specs if s["name"] == name)


# --- input models: strict, required, defaults --------------------------------

def test_input_models_are_strict_and_reject_unknown_fields():
    with pytest.raises(ValidationError):
        GetEncounterInput(encounter_id=1, bogus="x")
    with pytest.raises(ValidationError):
        EmptyToolInput(anything="x")


def test_get_encounter_input_requires_encounter_id():
    assert GetEncounterInput(encounter_id=5).encounter_id == 5
    with pytest.raises(ValidationError):
        GetEncounterInput()


def test_optional_inputs_have_defaults():
    assert GetMedicationsInput().active_only is False
    assert SearchChartInput(query="chest pain").limit == 20
    with pytest.raises(ValidationError):
        SearchChartInput()  # query is required


# --- derivation: input_schema IS the model's schema (source of truth) --------

def test_chart_tool_input_schemas_are_derived_from_models():
    b = FakeBoundary([])
    enc = build_encounter_tools(b)
    assert _tool_by_name(enc, "list_encounters")["input_schema"] == EmptyToolInput.model_json_schema()
    assert _tool_by_name(enc, "get_encounter")["input_schema"] == GetEncounterInput.model_json_schema()
    assert build_results_tool(b)["input_schema"] == EmptyToolInput.model_json_schema()
    assert build_medications_tool(b)["input_schema"] == GetMedicationsInput.model_json_schema()
    assert build_search_tool(b)["input_schema"] == SearchChartInput.model_json_schema()


def test_get_patient_summary_input_schema_is_derived_from_empty_model():
    agent = ClaudeAgent(lambda **k: None, lambda pid: {})
    summary_tool = _tool_by_name(agent._tools(), "get_patient_summary")
    assert summary_tool["input_schema"] == EmptyToolInput.model_json_schema()


# --- output models: known fields typed, extras ignored, wrong type rejected ---

def test_medication_row_types_known_fields_and_ignores_extras():
    row = MedicationRow.model_validate(
        {"ref": "prescription:1", "drug": "Warfarin", "active": True,
         "status_conflict": False, "surprise_new_field": "x"}
    )
    assert row.ref == "prescription:1"
    assert row.active is True


def test_medication_row_rejects_wrong_typed_known_field():
    with pytest.raises(ValidationError):
        MedicationRow.model_validate({"ref": "prescription:1", "active": "not-a-bool"})


def test_note_snippet_validates_known_fields():
    snip = NoteSnippet.model_validate(
        {"ref": "pnote:1", "source_type": "pnotes", "date": "2026-01-01", "snippet": "chest pain"}
    )
    assert snip.ref == "pnote:1"


def test_output_model_names_exist_for_every_tool():
    # Every tool result has a model (documented contract).
    for model in (PatientSummary, EncounterRow, LabResult, MedicationRow, NoteSnippet):
        assert hasattr(model, "model_validate")


# --- handlers validate output through the contract ---------------------------

def test_medications_handler_passes_a_valid_row_through_losslessly():
    good = [{"ref": "prescription:1", "active": True, "status_conflict": False, "extra": "keep"}]
    tool = build_medications_tool(FakeBoundary(good))
    out = tool["handler"](42, {})
    # The original data (including the unknown field) reaches the model unchanged.
    assert out[0]["ref"] == "prescription:1"
    assert out[0].get("extra") == "keep"


def test_medications_handler_raises_on_a_contract_violating_row():
    bad = [{"ref": "prescription:1", "active": "not-a-bool"}]
    tool = build_medications_tool(FakeBoundary(bad))
    with pytest.raises(Exception):
        tool["handler"](42, {})


# --- requirements declares pydantic ------------------------------------------

def test_pydantic_is_declared_in_requirements():
    req = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
    with open(req) as fh:
        assert "pydantic" in fh.read().lower()
