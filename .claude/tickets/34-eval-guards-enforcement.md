---
id: 34
title: Executable boundary/invariant/regression guards on every eval case
status: ready-for-merge
depends_on: []
branch: ticket/34-eval-guards-enforcement
base_branch: main
test_command: "python -m pytest sidecar/tests/test_eval_guards_enforcement.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
Engineering deliverable: "Every evaluation case must exercise a boundary
condition, an invariant, or a known regression risk. Happy-path-only test suites
do not pass. Document the failure mode each test guards against."

The eval suite already exercises boundaries/invariants/regressions, but the
guarded failure mode lives only in freeform comments and nothing ENFORCES the
rule. Make it executable: add a structured `guards` field to every eval case and
a meta-test that fails the suite if any packaged case lacks a valid guard.

## Acceptance criteria
- [ ] `EvalCase` gains an optional `guards` field; `load_cases` parses a case's
      `guards: {type, failure_mode}` mapping.
- [ ] EVERY packaged eval case (all `sidecar/evals/*.yaml`) declares a `guards`
      block with `type` in {`boundary`, `invariant`, `regression`} and a
      non-empty `failure_mode` string documenting what it guards against.
- [ ] A meta-test asserts: every packaged case has a valid `guards` annotation
      (valid type + non-empty failure_mode), and the suite as a whole covers all
      three types (each appears at least once). A case with no/invalid guard
      fails the suite (i.e. "happy-path-only does not pass" is CI-enforced).
- [ ] Grading behaviour is unchanged (guards is metadata; existing graders and
      the sweep/completeness tests stay green).

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_eval_guards_enforcement.py`
  - every packaged case has guards.type in the allowed set + non-empty failure_mode
  - all three guard types are represented across the suite
  - an invalid/missing guard is rejected (constructed case fails the rule helper)
