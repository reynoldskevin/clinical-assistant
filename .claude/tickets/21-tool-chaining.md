---
id: 021
title: Tool-chaining loop + max-tool-calls budget (+ chaining eval case)
status: ready-for-merge    # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [017]
branch: ticket/21-tool-chaining
base_branch: main          # branch off main (T20 merged); see skill decision #2
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Make the sidecar agent's multi-tool chaining explicit and bounded: the model can
chain tools across turns (e.g. `list_encounters` → `get_encounter` on the returned
id), and a **max-tool-calls budget** caps the total number of tool executions per
question so a turn can never run away — when the budget is spent the agent stops
offering tools and forces a final text answer.

## Design (sidecar `agent.py`)

- **Chaining already works** via the tool-use loop; this ticket locks it with a test
  (two tools chained across iterations, each dispatched with the FIXED session pid).
- **`max_tool_calls` budget** — a constructor param (sane default). Track cumulative
  tool executions across the turn. While `tool_calls_made < max_tool_calls`, offer the
  full tool catalog; once the budget is reached, make the next model call with **no
  tools** so the model must answer from what it has (never an infinite loop). The
  iteration safety cap is derived from the budget (budget + small margin) so the
  final no-tools call always happens before the loop bound.
- Budget is independent of, and stricter than, the raw iteration cap. `server.py`
  wires a default (optionally overridable via env); the built-in summary path and
  T12/T17 behaviour are unchanged when the budget isn't hit.

## Acceptance criteria
- [ ] The agent chains two tools across iterations (`list_encounters` then `get_encounter`), each called with the fixed pid; final text is returned.
- [ ] A `max_tool_calls` budget caps total tool executions: given a model that keeps calling tools, exactly `max_tool_calls` execute, then the agent calls the model with an empty tool list and returns its final text (no `RuntimeError`, no infinite loop).
- [ ] Under budget, tools are offered normally and a normal single/chained turn is unaffected.
- [ ] The budget is configurable; default is sane and does not break existing T12/T17 behaviour.
- [ ] A chaining/budget eval case (`sidecar/evals/uc8.yaml`) loads via the harness and its `max_tool_calls` grader enforces the cap.
- [ ] All prior sidecar tests still pass.

## Test plan (LOCKED — authored)
- `test_tool_chaining.py`: chains two tools across iterations (fixed pid); budget caps executions + forces a no-tools final answer; under-budget behaviour unaffected.
- Eval `test_uc8_evals.py` + `evals/uc8.yaml`: case loads with `tool_used` + `max_tool_calls` graders; the budget grader passes at/under the cap and fails over it.
