---
id: 018
title: Tool — get_results (lab/diagnostic results) (+ eval case)
status: tests-authored     # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [017]
branch: ticket/18-get-results
base_branch: main          # T17 is merged to main (c091c7b); T18 branches off main, not stacked
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Add the `get_results` chart tool: retrieve the patient's lab / diagnostic
results (value, units, reference range, abnormal flag, status, date) — a
dedicated, complete results view, distinct from the summary's capped
`recent_labs`. First tool to exercise the "add a tool = one enum case + one
provider method + one match arm + one ToolSpec" path the T17 boundary was
built for.

## Design (reuses the T17 multi-tool boundary — no new boundary machinery)

- **`ChartOperation`**: add one case `GetResults = 'get_results'`.
- **`ChartReadProviderInterface`**: add `getResults(int $pid): array`.
  `PatientSummaryService` implements it — pid-scoped join
  `procedure_result → procedure_report → procedure_order` on
  `procedure_order.patient_id = ?`, most-recent-first, returning
  `result_code, result_text, result, units, range, abnormal, date, result_status`.
- **`ChartReadEndpoint`**: add one match arm `GetResults → getResults($pid)`
  (still exhaustive, no default). Verify-before-read + audit are unchanged.
- **`public/read.php`**: NO change — it dispatches by `op` generically.
- **Sidecar**: add `chart_boundary.get_results(pid)` (POST `op=get_results`) and a
  `build_results_tool(chart_boundary)` ToolSpec; wire it into `server.py`'s
  `extra_tools`. `agent.py` is unchanged (generic `extra_tools`).
- **Eval**: a UC-5 results case (`sidecar/evals/uc5.yaml`).

### Contract evolution — two T17 tests are updated by the orchestrator (NOT the implementer)

Extending the enum + interface legitimately changes the T17 contract, so the
orchestrator updates these prior locked tests as part of THIS ticket's test commit
(the implementer still may not touch any test):
- `ChartOperationTest.php` — expected op set becomes the four ops (adds `get_results`).
- `ChartReadEndpointTest.php` — the fake provider implements `getResults`, and a
  `GetResults` dispatch + cross-pid case is added.

## Acceptance criteria

- [ ] `ChartOperation` has a fourth case `get_results`; the others are unchanged.
- [ ] `ChartReadProviderInterface::getResults(int $pid): array` exists; `PatientSummaryService` implements it.
- [ ] `getResults($pid)` returns ONLY that patient's results, most-recent-first, with `result_code, result_text, result, units, range, abnormal, date, result_status`.
- [ ] Cross-pid isolation: another patient's results never appear in `getResults($pid)`.
- [ ] `ChartReadEndpoint` dispatches `GetResults` to `getResults` via exhaustive match (no default); a denied token reads nothing for this op too.
- [ ] Sidecar: a `get_results` tool_use dispatches to a handler that calls `chart_boundary.get_results(pid)` with the fixed session pid; `build_results_tool` is well-formed; the boundary POSTs `{op:"get_results", pid, params:{}}` to read.php with the Bearer JWT.
- [ ] Server wires the results tool alongside the encounter tools (extra_tools).
- [ ] UC-5 eval case (`sidecar/evals/uc5.yaml`) loads/validates via the harness, exercising a lab-results question.
- [ ] All prior locked tests (T09*, T12–T17) still pass (with the two documented T17-test updates).

## Test plan (orchestrator authors these — LOCKED)

- **PHP unit (isolated, DB-backed)** — `ChartReadServiceResultsTest`: seed 2 patients with
  order→report→result rows; assert `getResults` scoping + ordering + fields + abnormal flag,
  and that patient 2's results never leak into patient 1's.
- **PHP unit (isolated, fakes)** — UPDATE `ChartReadEndpointTest`: fake provider gains
  `getResults`; add valid-token `GetResults` dispatch + cross-pid denial. UPDATE
  `ChartOperationTest`: four-op expected set + parse.
- **Sidecar unit** — `test_results_tool.py`: agent dispatches `get_results` to its handler
  with fixed pid; `build_results_tool` spec well-formed; `chart_boundary.get_results` POSTs
  `op=get_results` with Bearer (fake opener).
- **Eval** — `test_uc5_evals.py`: `uc5.yaml` loads and validates through the harness (structure/graders),
  requires tool use + results content, no live API call.
