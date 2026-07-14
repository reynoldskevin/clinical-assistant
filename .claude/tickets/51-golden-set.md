---
id: 51
title: 50-case golden set + 5 boolean rubric categories
status: tests-authored
depends_on: [50]
branch: ticket/51-golden-set
base_branch: main   # dep 50 already merged to main (2026-07-11); branched off main, not the stale ticket/50 branch
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_golden_set.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Week 2 Stage 4, requirement 4 (eval-driven). 50 synthetic/demo cases exercising extraction, evidence retrieval, citations, refusals, and missing-data behavior, with 5 boolean rubric categories: `schema_valid`, `citation_present`, `factually_consistent`, `safe_refusal`, `no_phi_in_logs`. Golden set lives in-repo (reproducible from the repo alone). Author cheaply via programmatic variations of a few templates, ≥1 case per rubric category (adversarial/extreme depth → T65).

## Acceptance criteria
- [ ] 50 cases load and run through the eval harness.
- [ ] All 5 boolean rubric categories implemented, each with ≥1 case and a pass threshold.
- [ ] Golden set reproducible from the repo alone (no external fetch).

## Test plan (orchestrator authors these)
- behavioral `sidecar/tests/test_golden_set.py`: dataset loads to exactly 50 cases; every rubric category represented; each rubric grader is boolean and wired; threshold enforced.
