---
id: 44
title: Eval dataset + test-suite results submission artifact
status: ready-for-merge
depends_on: [34]
branch: ticket/44-eval-dataset
base_branch: main
test_command: "python -m pytest sidecar/tests/test_eval_dataset_doc.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
Submission requirement: the eval dataset + the test suite with results (structure
and scope are our design decisions). `EVAL_DATASET.md` documents the dataset
(`sidecar/evals/*.yaml`, 21 cases), its structure/scope (UC-1..6, 7 categories,
boundary/invariant/regression guards, graders, offline+live modes), and the
captured results.

## Result
- Offline deterministic gate: **53/53 eval tests pass**; full sidecar suite
  **234/234**. 21/21 cases; UC-1..6 complete; all 7 categories; guards 4 boundary
  / 14 invariant / 3 regression.
- Live sweep documented as the production-parity check (needs API key + seeded pid
  + JWT); real agent behavior on chart questions also exercised by STRESS_TESTS.md.

## Acceptance criteria
- [x] EVAL_DATASET.md documents dataset structure, scope, and results with the
      per-case table.
- [x] Guard test pins the doc + keeps the "21 cases" count honest against the
      real dataset; full suite green.
