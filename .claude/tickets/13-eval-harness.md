---
id: 13
title: Eval harness + YAML case format + graders
status: tests-authored
depends_on: [12]
branch: ticket/13-eval-harness
base_branch: main
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests/test_eval.py"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description
The "prove it works" backbone: a small eval harness that loads YAML eval cases,
runs each against an injected agent-runner (so it's model-agnostic and deterministic
in tests — a real run wires the sidecar agent), and grades the output + trace.
T14/T15 add cases on top of this.

## Acceptance criteria
- [ ] `sidecar/eval.py`: `EvalCase` (name, question, pid: int, graders: list of grader specs);
      `load_cases(yaml_text: str) -> list[EvalCase]` parses a YAML list of cases.
- [ ] Graders (each a one-key dict spec) evaluated against `(text, trace)`:
      `{"contains": s}` (case-insensitive substring present), `{"excludes": s}` (absent),
      `{"tool_used": bool}` (trace tool_calls >= 1 iff true), `{"max_tool_calls": n}`
      (trace tool_calls <= n), `{"no_tool_failures": true}` (trace tool_failures == 0).
- [ ] `run_case(case, runner) -> EvalResult` where `runner(question, pid) -> (text, trace_dict)`;
      `EvalResult` has `name`, `passed` (all graders pass), and `failures` (list of reasons).
- [ ] `run_suite(cases, runner) -> dict` with `passed`, `total`, and per-case `results`.
- [ ] Unknown grader key is a hard failure (not silently passed).

## Test plan (orchestrator authors these — LOCKED)
- unit (`sidecar/tests/test_eval.py`, injected fake runner): YAML loads into cases;
  each grader passes/fails correctly against a canned (text, trace); run_case aggregates;
  run_suite tallies passed/total.

## Notes
`trace_dict` is `TraceCollector.summary()` shape (tool_calls, tool_failures, ...). A live
eval run (real Claude via the sidecar) is a separate execution, out of scope here.
