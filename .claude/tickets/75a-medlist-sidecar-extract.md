---
id: 075a
title: Sidecar med_list — third document type, strict-schema extraction
status: ready-for-merge
depends_on: []
branch: ticket/75a-medlist-sidecar-extract
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_extractor.py tests/test_openapi_spec.py tests/test_medlist_extract.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Add a third document type — a **medication list PDF** (`doc_type: "med_list"`) — to the sidecar extractor, following the exact pattern of `lab_pdf`/`intake_form`: store nothing new (the /extract path is doc-type-agnostic) and return strict-schema JSON. Add a `MedicationListFact` Pydantic contract (a flat human-readable `medications` string per the extractor's "combine into one string / no nested objects" rule, plus the mandatory non-empty `source_citation`), wire it into `_CONTRACTS`/`_DOC_INSTRUCTIONS`, add `med_list` to `server._DOC_TYPES` and the `ExtractRequest.doc_type` enum, and reflect it in `openapi.yaml`'s doc_type enum (the T60 contract test pins spec⇄model⇄server parity). Add a `generate_medication_list.py` fixture generator + a committed `synthetic_medication_list.pdf` mirroring `generate_lab_report.py`. Identity check stays intake-only (med_list, like lab_pdf, gets no identity_check).

## Acceptance criteria
- [ ] `contracts.MedicationListFact` is a STRICT (`extra="forbid"`) model with `medications: Optional[str]` (a single human-readable string, no nested objects/arrays) and `source_citation: str = Field(min_length=1)` — mirroring `LabFact`/`IntakeFact` (every named field required-as-key; a groundable-but-absent value is explicit `null`, surfaced via `unsupported_fields`, never invented).
- [ ] `ExtractRequest.doc_type` Literal, `server._DOC_TYPES`, and the `openapi.yaml` `/extract` `doc_type` enum ALL include `med_list` (the locked `test_openapi_spec.py::test_doc_type_enum_matches_server_doc_types` asserts these three are equal).
- [ ] `extractor._CONTRACTS["med_list"] == MedicationListFact` and `_DOC_INSTRUCTIONS["med_list"]` gives a medication-list extraction prompt (one medication per entry, `'; '`-separated, `drug dose route frequency`); `attach_and_extract(..., doc_type="med_list", ...)` returns an `ExtractionResult` with `doc_type="med_list"`, the validated `MedicationListFact`, and `unsupported_fields` derived (source_citation exempt).
- [ ] `default_extract_builder`'s `/extract` returns the standard envelope for `med_list` (ok/doc_type/confidence/low_confidence/unsupported_fields/fact/correlation_id) and emits `ingestion.start`/`ingestion.complete`; NO `identity_check` for med_list (intake-only).
- [ ] `sidecar/fixtures/documents/generate_medication_list.py` produces a text-based `synthetic_medication_list.pdf` (fpdf2, each medication a distinct text run) listing a few realistic meds; the PDF is committed.

## Test plan (orchestrator authors these)
- Extend `sidecar/tests/test_extractor.py` — a `MedicationListFact` strict-schema test (all named fields required; `extra="forbid"` rejects unknowns; empty `source_citation` rejected) analogous to the LabFact/IntakeFact tests.
- `test_openapi_spec.py::test_doc_type_enum_matches_server_doc_types` is the LOCKED parity guard — it passes once `_DOC_TYPES` + the Literal + the openapi enum include `med_list`.
- `sidecar/tests/test_medlist_extract.py` (new) — a scripted `message_creator` returns a med-list envelope; `attach_and_extract(doc_type="med_list")` yields the `MedicationListFact` + correct result fields; and a `default_extract_builder` round-trip (stubbed boundary/extractor) returns the envelope with NO `identity_check` and emits the ingestion events.
