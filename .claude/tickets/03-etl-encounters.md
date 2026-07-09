---
id: 03
title: ETL encounters → form_encounter + forms
status: tests-authored
depends_on: [02]
branch: ticket/03-etl-encounters
base_branch: main
test_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl/tests/test_etl_encounters.py -q"
full_suite_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl -q"
attempts: 0
---

## Description
Parse Synthea Encounter resources from a patient bundle and load them into OpenEMR
`form_encounter`, plus a `forms` registry row per encounter (formdir=`newpatient`,
`form_id`→the encounter's id) so OpenEMR treats them as real visits. Encounters
link to the already-loaded patient (from T02) via the bundle's Patient uuid → pid.

## Acceptance criteria
- [ ] For a bundle whose patient is already in `patient_data`, each Encounter →
      one `form_encounter` row (pid, a unique `encounter` number, date from
      period.start, reason from type[0].text) AND one `forms` registry row
      (pid, same encounter, formdir='newpatient', form_id=form_encounter.id, deleted=0).
- [ ] Encounter numbers are unique (globally MAX(encounter)+1).
- [ ] Idempotent: re-running the same bundle inserts no duplicates (dedup by the
      Encounter's uuid stored on form_encounter.uuid).
- [ ] Skips encounters whose patient is NOT in `patient_data` (returns 0 inserted).

## Test plan (orchestrator authors these — LOCKED)
- integration (`etl/tests/test_etl_encounters.py`, throwaway schema cloning
  patient_data, uuid_registry, form_encounter, forms): create form_encounter+forms
  rows correctly linked; idempotency; unique encounter numbers; skip-when-no-patient.

## Notes
Synthea bundles are single-patient; link all encounters in a bundle to that
patient's pid. Uses T02's `etl_patients.load_bundles` to set up the patient in tests.
