---
id: 33
title: System-prompt task-framing nudge for UC-4 (longitudinal) + UC-5 (draft)
status: ready-for-merge
depends_on: [32]
branch: ticket/33-prompt-uc4-uc5-nudge
base_branch: main
test_command: "python -m pytest sidecar/tests/test_system_prompt_task_framing.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
The T32 UC-4 (longitudinal-pattern) and UC-5 (draft-ownership) eval cases only
pass on the LIVE sweep if the agent actually synthesizes a pattern across prior
encounters and frames handoffs as drafts to verify — behaviour driven by the
system prompt, which did not instruct either. Add a "Task framing" section to
`_SYSTEM_PROMPT`.

Prompt behaviour has no deterministic unit test (offline evals use injected
runners; real validation is the live sweep). Locked with GUARD tests that pin the
two instructions into the prompt so a future edit can't silently drop them.

## Acceptance criteria
- [ ] `_SYSTEM_PROMPT` instructs longitudinal PATTERN synthesis across prior
      encounters (not just listing that visits exist) and explicitness about
      which prior history could/couldn't be found.
- [ ] `_SYSTEM_PROMPT` instructs presenting handoffs/sign-outs as a DRAFT for the
      physician to verify and own, flagging pending/uncertain items.
- [ ] The existing grounding + data-quality contract is preserved.
- [ ] Full sidecar suite stays green (offline behaviour unchanged — the prompt is
      only read on the live path).

## Test plan (orchestrator authors these)
- guard: `sidecar/tests/test_system_prompt_task_framing.py` — asserts the two new
  framing clauses are present and the existing contract (citations,
  openemr:_absence, empty != absent) is retained.
