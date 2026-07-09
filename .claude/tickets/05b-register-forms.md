---
id: 05b
title: Register vitals/labs as encounter forms (UI visibility)
status: ready-for-merge
depends_on: [05]
branch: ticket/05b-register-forms
base_branch: ticket/05-etl-observations
test_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl/tests/test_etl_forms.py -q"
full_suite_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl -q"
attempts: 0
---

## Description
After T05 loads vitals/labs into `form_vitals` and the `procedure_*` chain, the
data isn't linked to an encounter, so OpenEMR's encounter UI doesn't render it.
This ticket adds `etl_forms.register_forms(bundles, conn)` — a pass that links the
already-loaded vitals/labs to their encounters via the `forms` registry (and
`procedure_order.encounter_id`), so charts render in the app.

## Acceptance criteria
- [ ] Vitals: for each vital-signs Observation group, resolve its Observation
      `encounter` reference → the `form_encounter.encounter` number (via
      form_encounter.uuid), find the matching `form_vitals` row (pid+date), and
      INSERT a `forms` row (formdir='vitals', form_name='Vitals',
      form_id=form_vitals.id, pid, encounter, date, deleted=0).
- [ ] Labs: for each laboratory Observation, resolve its encounter, find the
      `procedure_order` (via result_code+date+patient), set
      `procedure_order.encounter_id`, and INSERT a `forms` row
      (formdir='procedure_order', form_name='Procedure Order',
      form_id=procedure_order_id, pid, encounter, date, deleted=0).
- [ ] Returns `{'vitals': v, 'labs': l}` counting forms rows registered.
- [ ] Idempotent: re-run adds no duplicate forms rows.
- [ ] Skips gracefully when the encounter reference can't be resolved.

## Test plan (orchestrator authors these — LOCKED)
- integration (`etl/tests/test_etl_forms.py`, throwaway schema cloning patient_data,
  uuid_registry, form_encounter, forms, form_vitals, procedure_order/report/result):
  set up via load_patients+load_encounters+load_observations on a bundle whose
  observations carry encounter refs, then register_forms; assert forms(vitals) +
  forms(procedure_order) rows + procedure_order.encounter_id set; idempotency.

## Notes
Pure post-pass over T05's output; does not modify the T05 loaders. The live load
script calls it after load_observations so charts render at localhost:8300.
