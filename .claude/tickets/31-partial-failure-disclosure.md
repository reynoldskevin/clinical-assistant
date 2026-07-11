---
id: 31
title: Partial-failure disclosure — surface mid-turn tool failures to the clinician
status: todo
depends_on: []
branch: ticket/31-partial-failure-disclosure
base_branch: main
test_command: "python -m pytest sidecar/tests/test_partial_failure_disclosure.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description
When a tool fails mid-turn, the agent already degrades gracefully: the failure is
caught, an `is_error` tool_result is fed back, and the loop continues so the model
can answer around the gap. But that partial failure is invisible to the clinician
— the model is *told* a lookup failed, yet whether it discloses that is
non-deterministic, so a degraded answer can present as authoritative. The brief
(Failure Modes): *"A clinical tool that … silently fails is worse than no tool at
all. Graceful degradation, transparent errors."*

Close it the same deterministic way T30 closed silent truncation: when any tool
returned `is_error` during the turn, tell the caller.

## Acceptance criteria
- [ ] When the final answer is produced and at least one tool returned `is_error`
      during the turn (a boundary/handler exception, or an unknown tool), the
      returned answer carries a partial-failure disclosure — a plain, digit-free,
      citation-free notice appended AFTER the verification gate. The notice
      contains the phrase "may be incomplete".
- [ ] In that same case, when `on_event` is supplied, a
      `{"type": "degraded", "reason": "tool_failure"}` event is emitted (once).
- [ ] When every tool call succeeds, NO disclosure is appended and NO degraded
      event is emitted (byte-for-byte today's answer).
- [ ] Backward compatible: with `on_event=None`, a failed-tool turn still appends
      the disclosure and does not crash.
- [ ] The clinical answer text is preserved — the disclosure is additive.
- [ ] Independent of T30: a failed-tool turn under budget is `degraded` but NOT
      `truncated`; the two disclosures compose without interfering.

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_partial_failure_disclosure.py`
  - handler raises -> "may be incomplete" + degraded event (reason tool_failure)
  - get_patient_summary boundary raises -> degraded
  - unknown tool -> degraded
  - all tools succeed -> no notice, no degraded event
  - on_event=None with a failure -> notice present, no crash
  - clinical text preserved alongside the notice
  - degraded (under budget) is not also truncated
