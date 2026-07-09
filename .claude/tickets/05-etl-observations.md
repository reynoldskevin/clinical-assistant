---
id: 05
title: ETL observations → form_vitals / procedure_result
status: tests-authored
depends_on: [04]
branch: ticket/05-etl-observations
base_branch: ticket/04-etl-clinical
test_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl/tests/test_etl_observations.py -q"
full_suite_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl -q"
attempts: 0
---

## Description
Parse Synthea `Observation` resources and load them:
- category `vital-signs` → `form_vitals` (one row per patient+datetime, LOINC→column)
- category `laboratory` → the `procedure_order` → `procedure_report` → `procedure_result` chain
Entry point `load_observations(bundles, conn) -> {'vitals': n, 'labs': n}`.

## Acceptance criteria
- [ ] Vital-signs observations sharing an effectiveDateTime aggregate into ONE
      `form_vitals` row (pid, date). LOINC→column: 8480-6→bps, 8462-4→bpd,
      29463-7→weight, 8867-4→pulse (bps/bpd are varchar → store integer strings).
- [ ] Handles the BP panel (LOINC 85354-9) with `component[]` (systolic 8480-6 /
      diastolic 8462-4) AND standalone vital observations.
- [ ] Each laboratory observation → a `procedure_order` (patient_id=pid) +
      `procedure_report` (order link) + `procedure_result` (report link) with
      result_code=LOINC, result=value, units, result_text=display.
- [ ] `load_observations` returns `{'vitals': n_vital_rows, 'labs': n_result_rows}`.
- [ ] Idempotent: re-run inserts nothing (vitals dedup by pid+date; labs by pid+result_code+date).
- [ ] Skips the whole bundle when its patient is not in `patient_data`.

## Test plan (orchestrator authors these — LOCKED)
- integration (`etl/tests/test_etl_observations.py`, throwaway schema cloning
  patient_data, uuid_registry, form_vitals, procedure_order/report/result):
  vitals aggregation + BP components + LOINC→column; lab chain linked to pid;
  idempotency; skip-when-no-patient.

## Notes
Single-patient Synthea bundles → link to that pid (as T03/T04). `procedure_order`
requires patient_id, `procedure_result` requires procedure_report_id (strict mode).
UI registration of vitals as a `forms` row is a possible follow-up; the agent reads
these tables directly.
