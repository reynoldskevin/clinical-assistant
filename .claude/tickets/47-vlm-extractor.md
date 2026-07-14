---
id: 47
title: VLM extractor → strict LabFact/IntakeFact schemas (canonical contract)
status: tests-authored
depends_on: [46]
branch: ticket/47-vlm-extractor
base_branch: ticket/46-ui-upload
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_extractor.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Claude vision reads a stored document (fetched via the T46 `get_document` boundary op) and returns strict `LabFact` / `IntakeFact` Pydantic models — the canonical extraction contracts (`model_json_schema()` exported). Raw VLM output is validated before any downstream use and never bypasses the contract. The "no invention" bar is in scope: unsupported / low-confidence fields are flagged, never invented. Happy path only: optimize for a clean scan (degraded/rotated/noisy → T63).

## Acceptance criteria
- [ ] `LabFact` required fields: test name, value, unit, reference range, collection date, abnormal flag, source citation.
- [ ] `IntakeFact` required fields: demographics, chief concern, current medications, allergies, family history, source citation.
- [ ] `attach_and_extract(patient_id, document_id, doc_type)` fetches the stored doc via the boundary and returns schema-valid objects on a clean lab PDF + clean intake form.
- [ ] Raw VLM output is validated through the model; a deliberately-hallucinated-field negative test proves validation catches it.
- [ ] Extraction confidence recorded (PHI-free).
- [ ] Committed synthetic fixtures under `sidecar/fixtures/documents/` (one clean lab PDF, one intake form; synthetic, no PHI).

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_extractor.py`: stubbed VLM client returns a fixture payload → schema-valid LabFact/IntakeFact; hallucinated/unsupported field flagged not invented; missing required field raises; confidence recorded and PHI-free.
- extend `test_contracts.py`: LabFact/IntakeFact strictness + json-schema export.
