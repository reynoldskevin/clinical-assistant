---
id: 02
title: ETL patients → patient_data (+ uuid_registry)
status: ready-for-merge
depends_on: [01]
branch: ticket/02-etl-patients
base_branch: ticket/01-synthea-gen
test_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl/tests/test_etl_patients.py -q"
full_suite_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl -q"
attempts: 1
---

## Description
Parse Synthea patient FHIR bundles (from T01) and insert demographics into OpenEMR
`patient_data`, registering each in `uuid_registry`. Integration-tested against a
disposable throwaway MySQL schema; final load target = local dev OpenEMR
(development-easy MySQL, db `openemr`).

## Acceptance criteria
- [ ] Parse a Synthea Patient resource → OpenEMR demographic fields
      (fname, lname, DOB, sex, race, ethnicity, address, phone; map codes; unknown → "" / not fabricated).
- [ ] Insert one `patient_data` row per patient with a fresh `pid`; register a UUID in `uuid_registry`.
- [ ] Idempotent: re-running the same bundle does not create duplicates.
- [ ] Loads a cohort into the target DB; patients are queryable (count matches input).

## Test plan (orchestrator authors these — LOCKED)
- integration (`etl/tests/test_etl_patients.py`, throwaway schema):
  field mapping from a fixture bundle; pid + uuid_registry row created; idempotency on re-run;
  unmapped race code → empty, not invented.

## Notes
TDD uses a disposable schema (created/dropped per test). The live load into
`openemr` is a final step, separate from the test suite.
