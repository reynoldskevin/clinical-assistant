"""Canonical Pydantic contracts for every sidecar tool.

These models are the single source of truth for tool inputs and outputs: each
tool's advertised ``input_schema`` is derived from its input model via
``model_json_schema()``, handlers parse their input through the input model, and
handlers validate their output through the output model. Input models are strict
(unknown fields rejected); output models type only the known fields and ignore
unknowns, so a new PHP-side field never breaks a turn. Validation helpers
validate-and-passthrough: they raise on a contract violation but return the
ORIGINAL data unchanged, so nothing (including unknown fields) is dropped from
what the agent ultimately receives.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, TypeAdapter


# --- INPUT models (strict: unknown fields rejected) --------------------------

class EmptyToolInput(BaseModel):
    """No-argument tool input (get_patient_summary, list_encounters, get_results)."""

    model_config = ConfigDict(extra="forbid")


class GetEncounterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter_id: int


class GetMedicationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_only: bool = False


class SearchChartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    limit: int = 20


# --- OUTPUT models (extras ignored; known fields typed, Optional) ------------

class MedicationRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: Optional[str] = None
    drug: Optional[str] = None
    rxnorm: Optional[str] = None
    active: Optional[bool] = None
    status_conflict: Optional[bool] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class NoteSnippet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: Optional[str] = None
    source_type: Optional[str] = None
    date: Optional[str] = None
    snippet: Optional[str] = None


class EncounterRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: Optional[str] = None
    date: Optional[str] = None
    reason: Optional[str] = None


class LabResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: Optional[str] = None
    value: Optional[str] = None
    units: Optional[str] = None
    reference_range: Optional[str] = None
    abnormal: Optional[str] = None
    status: Optional[str] = None
    date: Optional[str] = None


class PatientSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    demographics: Optional[dict] = None
    problems: Optional[list] = None
    medications: Optional[list] = None
    allergies: Optional[list] = None
    vitals: Optional[list] = None


# --- validate-and-passthrough helpers ----------------------------------------

def validate_rows(model, rows):
    """Validate a list of rows against ``model``; return the ORIGINAL rows.

    Raises on a contract violation (a wrong-typed known field). The data is
    returned unchanged so unknown fields are never dropped downstream.
    """
    TypeAdapter(list[model]).validate_python(rows)
    return rows


def validate_obj(model, obj):
    """Validate a single object against ``model``; return the ORIGINAL object."""
    model.model_validate(obj)
    return obj
