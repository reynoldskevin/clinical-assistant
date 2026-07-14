---
id: 52
title: PR-blocking CI gate (>5% regression + schema/contract/extraction + offline integration)
status: ready-for-merge
depends_on: [51]
branch: ticket/52-ci-gate
base_branch: main   # dep 51 merged to main (MR !78); branched off main, not stacked
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_ci_gate.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Extend the Week 1 eval CI gate: fail the build if any rubric category regresses >5% or drops below its pass threshold. Add to the blocking suite: schema-validation tests, the supervisor↔worker contract test, extraction regression tests, and full ingestion→answer integration tests using fixture documents + stubbed LLM/VLM (pass in CI with no live keys). Dependency audit / security scan → T66.

## Acceptance criteria
- [x] CI fails when any category regresses >5% or drops below threshold (seeded regression proves it).
- [x] Blocking suite includes: schema validation, supervisor↔worker contract, extraction regression, ingestion→answer integration on fixtures with stubbed LLM/VLM.
- [x] Offline suite needs no secrets/network.

## Test plan (orchestrator authors these)
- integration/CI `sidecar/tests/test_ci_gate.py`: a seeded >5% regression fails the gate; the offline fixture+stub ingestion→answer path runs green with no keys; `.gitlab-ci.yml` wires the extended blocking job.
