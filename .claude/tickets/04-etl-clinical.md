---
id: 04
title: ETL conditions/allergies/meds/immunizations → lists/prescriptions/immunizations
status: ready-for-merge
depends_on: [03]
branch: ticket/04-etl-clinical
base_branch: ticket/03-etl-encounters
test_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl/tests/test_etl_clinical.py -q"
full_suite_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl -q"
attempts: 0
---

## Description
Parse the clinical resources in a Synthea patient bundle and load them:
- `Condition` → `lists` (type=`medical_problem`)
- `AllergyIntolerance` → `lists` (type=`allergy`)
- `MedicationRequest` → `prescriptions`
- `Immunization` → `immunizations`
All linked to the already-loaded patient (uuid→pid). One entry point
`load_clinical(bundles, conn) -> dict` with per-type counts.

## Acceptance criteria
- [ ] Condition → `lists` row: pid, type='medical_problem', title from code.text,
      diagnosis = `SNOMED-CT:<code>` (Synthea uses SNOMED), begdate from onsetDateTime, activity=1.
- [ ] AllergyIntolerance → `lists` row: type='allergy', title, diagnosis from its coding, activity=1.
- [ ] MedicationRequest → `prescriptions` row: patient_id=pid, drug from text,
      rxnorm_drugcode = the RxNorm code, active=1, date_added/start_date/txDate from authoredOn.
      (Must also supply the NOT-NULL-no-default cols `txDate`, `usage_category_title`, `request_intent_title`.)
- [ ] Immunization → `immunizations` row: patient_id=pid, cvx_code from vaccineCode,
      administered_date from occurrenceDateTime, update_date=NOW().
- [ ] `load_clinical` returns `{'problems':n,'allergies':n,'medications':n,'immunizations':n}`.
- [ ] Idempotent: re-run inserts nothing (dedup by each target table's `uuid` = the FHIR resource id).
- [ ] Skips the whole bundle when its patient is not in `patient_data`.

## Test plan (orchestrator authors these — LOCKED)
- integration (`etl/tests/test_etl_clinical.py`, throwaway schema cloning patient_data,
  uuid_registry, lists, prescriptions, immunizations): all-types load + row assertions;
  code mapping (SNOMED/RxNorm/CVX); idempotency; skip-when-no-patient.

## Notes
Single-patient Synthea bundles → link all clinical resources to that patient's pid
(same approach as T03). Uses T02's loader to set up the patient in tests.
