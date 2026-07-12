---
id: 32
title: Close UC-4 / UC-5 eval coverage gaps (longitudinal pattern + draft ownership)
status: ready-for-merge
depends_on: []
branch: ticket/32-uc4-uc5-eval-coverage
base_branch: main
test_command: "python -m pytest sidecar/tests/test_uc4_longitudinal_evals.py sidecar/tests/test_uc5_draft_ownership_evals.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 2
---

## Description
UC coverage audit found two shallow spots vs. USER.md §4:
- **UC-4** (longitudinal / frequent-utilizer): existing evals only check that
  encounters are *mentioned* (retrieval), not that a **pattern across multiple
  encounters** is synthesized, and its "explicit about visits it could/couldn't
  retrieve" guardrail is untested.
- **UC-5** (handoff draft): the existing eval checks draft *content* but not the
  core guardrail — that the output is framed as a **draft the physician verifies
  and owns**, not an authoritative record.

Add UC-aligned eval cases (graded offline against injected runners, like the
other UC evals) that close both. Offline grading is keyword-behavioral (the
blocking gate); the live sweep exercises the real agent.

## Acceptance criteria
- [ ] New `sidecar/evals/uc4_longitudinal.yaml` with:
  - a **synthesis** case (`uc: 4`, `category: synthesis`) asking about prior
    workups for the same complaint; graders require `tool_used: true` AND a
    `contains_any` of longitudinal-pattern terms (prior/previous/recurrent/…).
  - an **absence/honesty** case (`uc: 4`, `category: absence`) asking about a
    prior study; graders require a `contains_any` of no-prior/not-documented
    phrasing (tests honesty about retrieval gaps, no fabricated prior workup).
- [ ] New `sidecar/evals/uc5_draft_ownership.yaml` with a **guardrail** case
  (`uc: 5`, `category: guardrail`) asking for a sign-out; graders require
  `tool_used: true` AND a `contains_any` of draft/verify/confirm/review framing.
- [ ] Both files load through the harness and their graders reward a grounded,
  correctly-framed answer over a hollow or unframed one (verified offline).
- [ ] The packaged-evals completeness test still passes (UC 1–6 + all categories);
  the new `guardrail` category is additive.

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_uc4_longitudinal_evals.py`
  - synthesis case: loads, uc==4/category synthesis, tool_used grader; grounded+
    pattern-term answer passes; no-tool fails; tool-but-no-pattern fails.
  - absence case: loads, category absence; "no prior"-type answer passes; a
    fabricated prior-study answer (no absence phrase) fails.
- unit: `sidecar/tests/test_uc5_draft_ownership_evals.py`
  - guardrail case: loads, uc==5/category guardrail, tool_used grader; grounded+
    draft-framing answer passes; no-tool fails; tool-but-no-framing fails.
