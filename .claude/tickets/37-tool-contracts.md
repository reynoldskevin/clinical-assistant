---
id: 37
title: Canonical Pydantic contracts for every tool input and output
status: todo
depends_on: []
branch: ticket/37-tool-contracts
base_branch: main
test_command: "python -m pytest sidecar/tests/test_contracts.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description
Deliverable: strict schemas for every tool input and output; contracts are the
source of truth, not the implementation. Today the tool input JSON Schemas are
hand-written inline in factory.py (separate from the handler parsing — two
sources), and tool outputs have no schema at all.

Add `sidecar/contracts.py` with Pydantic v2 models for every tool input and
output, and make them canonical: the `input_schema` each tool advertises to
Claude is DERIVED from its input model (`model_json_schema()`), handlers PARSE
model-supplied input through the input model, and handlers VALIDATE boundary
output through the output model (typed known fields, unknown fields ignored so a
new PHP field never breaks a live turn; the original data is returned unchanged so
nothing is dropped). Declare `pydantic` explicitly in requirements.txt.

## Acceptance criteria
- [ ] `contracts.py` defines input models: `EmptyToolInput` (no args, strict),
      `GetEncounterInput` (encounter_id:int), `GetMedicationsInput`
      (active_only:bool=False), `SearchChartInput` (query:str, limit:int=20).
      Input models are STRICT (`extra="forbid"`): an unknown field is rejected.
- [ ] `contracts.py` defines output models for every tool result:
      `PatientSummary`, `EncounterRow`, `LabResult`, `MedicationRow`,
      `NoteSnippet` (typed known fields; `extra="ignore"`; unknown fields do not
      raise; a wrong-typed KNOWN field does raise).
- [ ] Every tool's advertised `input_schema` EQUALS its input model's
      `model_json_schema()` — get_patient_summary/list_encounters/get_results use
      `EmptyToolInput`; get_encounter/get_medications/search_chart use their
      models. No hand-written duplicate remains.
- [ ] Handlers parse input through the input model and validate output through the
      output model; a contract-violating boundary row surfaces as an error (raises,
      so the agent's tool-error path handles it); a valid row passes through with
      unknown fields preserved.
- [ ] `pydantic` is declared in `sidecar/requirements.txt`.
- [ ] No behaviour regression (full sidecar suite green).

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_contracts.py`
  - input models: strict (reject extra), required/defaults enforced
  - derivation: each tool's input_schema == model.model_json_schema()
  - output models: known field typed, extra ignored, wrong-typed known rejected
  - handler validates output: good row passes (extras preserved), bad row raises
  - requirements.txt declares pydantic
