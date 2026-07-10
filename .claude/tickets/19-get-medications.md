---
id: 019
title: Tool — get_medications (stale-active flag) (+ eval case)
status: tests-authored     # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [018]
branch: ticket/19-get-medications
base_branch: main          # branch off main (T18 merged); see skill decision #2
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Add the `get_medications` chart tool: retrieve the patient's medications with a
**stale-active** data-quality flag, on the existing T17/T18 multi-tool boundary.
This is the first tool to carry an explicit data-quality signal (the broader
data-quality theme lands in T27).

## Design (per ARCHITECTURE.md §2.5)

- **`get_medications`** returns `prescriptions` (+ medication-type `lists`) rows as
  `{ref, drug, rxnorm, active, start_date, end_date}`.
- **stale-active flag — the key nuance.** A row is *stale-active* when
  **`active = true` AND `end_date < today`**: the record is flagged active, but its
  own end date has already passed — the two facts contradict each other. Such rows
  are marked **`"status_conflict": true`** (per `DATA_QUALITY_AUDIT.md`).
  - **Why:** real EHR data routinely leaves `active = 1` long after a med is actually
    discontinued (nobody flips the flag). Trusting `active` alone would have the agent
    confidently report a discontinued med as "currently taking" — a plausible-but-wrong
    answer that's a patient-safety concern. So the tool neither over-reports (blindly
    trusting `active`) nor hides the row (dropping stale ones); it **surfaces the row
    AND marks the conflict**, so the agent can hedge ("listed active, but its end date
    was 2023 — may be stale").
- Reuses the boundary shape: one `ChartOperation` case (`get_medications`) + one
  provider method + one match arm + one ToolSpec. Contract-test the sidecar↔read.php
  payload shape (bare array), per skill decision #12.
- Input carries an optional `active_only?` per the spec.

## Acceptance criteria
- [ ] `ChartOperation` gains `get_medications` (5th op); interface gains `getMedications(int $pid, bool $activeOnly): array`; `ChartReadEndpoint` dispatches it via exhaustive match, reading `active_only` from params (defaults false).
- [ ] `getMedications($pid, $activeOnly)` unions `prescriptions` + medication-type `lists` rows for that patient only, returning `{ref, drug, rxnorm, active, start_date, end_date, status_conflict}` with `active`/`status_conflict` as bools.
- [ ] `status_conflict = true` iff the row is active AND its `end_date` is non-empty and before today; inactive rows and rows with no/future end_date are never flagged.
- [ ] `active_only = true` drops inactive rows but keeps (flagged) stale-active ones; cross-pid isolation holds.
- [ ] Sidecar: `ChartBoundary.get_medications(pid, active_only=False)` POSTs `{op:"get_medications", pid, params:{active_only}}` and accepts a BARE ARRAY (decision #12); `build_medications_tool` ToolSpec has an optional `active_only` boolean and dispatches with the fixed pid.
- [ ] UC-6 eval case rewards surfacing the stale-active conflict (tool use + a staleness hedge) over flatly asserting the med is current.
- [ ] All prior locked tests still pass (with the ChartOperationTest/ChartReadEndpointTest updates for the 5th op).

## Test plan (LOCKED — authored)
- PHP DB-backed `ChartReadServiceMedicationsTest`: stale-active matrix (active+past→conflict, active+future/none→no conflict, inactive→no conflict), prescriptions+lists union, active_only, cross-pid.
- PHP updates: `ChartOperationTest` (5 ops), `ChartReadEndpointTest` (fake `getMedications` + dispatch with/without `active_only`; cross-pid loop already iterates `cases()`).
- Sidecar `test_medications_tool`: boundary POST shape + bare-array contract + ToolSpec dispatch/defaults.
- Eval `test_uc6_evals` + `evals/uc6.yaml`.
