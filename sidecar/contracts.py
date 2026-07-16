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
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


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


class EvidenceQueryInput(BaseModel):
    """Evidence-retriever tool input (guideline corpus hybrid RAG)."""

    model_config = ConfigDict(extra="forbid")

    query: str
    top_k: int = 3


class GetIntakeFactInput(BaseModel):
    """Intake-form extraction tool input.

    ``document_id`` is optional: when omitted the tool extracts from the
    patient's most-recent uploaded intake form. Supply it (from get_documents)
    to target a specific intake form when several exist.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[int] = None


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


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    name: Optional[str] = None
    mimetype: Optional[str] = None
    docdate: Optional[str] = None
    doc_type: Optional[str] = None


class DocumentContent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    mimetype: Optional[str] = None
    doc_type: Optional[str] = None
    document_data: Optional[str] = None


class PatientSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    demographics: Optional[dict] = None
    problems: Optional[list] = None
    medications: Optional[list] = None
    allergies: Optional[list] = None
    vitals: Optional[list] = None


# --- STRICT extraction contracts (VLM output; schema is the source of truth) --

class LabFact(BaseModel):
    """A single lab result extracted from a document by the VLM.

    STRICT contract (``extra="forbid"``): the VLM cannot smuggle unknown fields,
    and every named field is a required KEY. Groundable-but-absent fields are
    typed ``Optional[str]`` with NO default, so a value the VLM cannot ground is
    explicitly ``null`` (and surfaced via ``unsupported_fields``), never invented
    or silently defaulted. ``source_citation`` is required AND non-null with a
    ``min_length`` constraint — grounding is mandatory, empty strings rejected.
    """

    model_config = ConfigDict(extra="forbid")

    test_name: Optional[str]
    value: Optional[str]
    unit: Optional[str]
    reference_range: Optional[str]
    collection_date: Optional[str]
    abnormal_flag: Optional[str]
    source_citation: str = Field(min_length=1)


class IntakeFact(BaseModel):
    """Structured intake-form facts extracted from a document by the VLM.

    STRICT contract (``extra="forbid"``): unknown fields rejected, every named
    field a required KEY, groundable-but-absent fields ``null`` (not invented).
    ``source_citation`` is required, non-null, and non-empty (``min_length``).
    """

    model_config = ConfigDict(extra="forbid")

    demographics: Optional[str]
    chief_concern: Optional[str]
    current_medications: Optional[str]
    allergies: Optional[str]
    family_history: Optional[str]
    source_citation: str = Field(min_length=1)


class ExtractionEnvelope(BaseModel):
    """The whole VLM extraction envelope, parsed strictly before the fact is.

    "Parse, don't validate": the raw JSON the VLM returns is turned into this
    typed model at the boundary, so downstream code works with values that
    already guarantee their own validity.

    * ``confidence`` is a float constrained to ``[0, 1]`` — an out-of-range,
      non-numeric, missing, or ``None`` confidence raises ``ValidationError``.
    * ``unsupported_fields`` is a list of field names, defaulting to ``[]``. A
      non-list (e.g. a bare string) raises ``ValidationError`` rather than being
      coerced into a per-character list.
    * ``fact`` is the raw fact object (validated against the doc-type contract
      downstream); a non-object (e.g. a string) raises ``ValidationError`` here.
    """

    model_config = ConfigDict(strict=True)

    confidence: float = Field(ge=0, le=1)
    unsupported_fields: list[str] = Field(default_factory=list)
    fact: dict[str, Any]


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
