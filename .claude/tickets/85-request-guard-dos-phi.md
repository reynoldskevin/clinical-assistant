---
id: 085
title: input guardrail refuses DoS/manipulation prompts without leaking PHI
status: ready-for-merge
depends_on: []
branch: ticket/85-request-guard-dos-phi
base_branch: main
test_command: "docker exec w2-guard-test python -m pytest tests/test_request_guard.py tests/test_agent_request_guard.py -q"
full_suite_command: "docker exec w2-guard-test python -m pytest -q"
attempts: 0
---

## Description
Two red-team findings (VULN-denial_of_service-9a0c65e6, -06edd052) showed the Co-Pilot correctly refusing a denial-of-service prompt (a 1000-call tool loop; a never-terminating per-sentence confirm/re-verify cycle) but, in the same turn, spontaneously disclosing scoped-patient PHI — lab values with result IDs, encounter notes, and the patient's sex, birth year, and active medications. The DoS mechanism was already bounded by the agent's per-turn tool budget, so the residual defect is the PHI leak: an adversarial control/meta-process request reaches the model, which then helpfully summarizes chart data. This ticket adds a deterministic input guardrail that classifies these manipulation/DoS control instructions and, when one is detected, short-circuits the turn to a fixed PHI-free refusal that makes zero model and zero tool calls — so no chart data is ever fetched or emitted on that turn — plus a defense-in-depth system-prompt clause telling the model never to volunteer chart PHI when declining such a request. The guardrail is a pure, offline, stdlib-only classifier with tight, low-false-positive patterns so ordinary clinical questions (including ones that mention numbers, "again", or "previous N visits") are never blocked.

## Acceptance criteria
- [ ] A pure module `sidecar/request_guard.py` exposes `classify_request(question: str) -> RequestGuardVerdict` (frozen dataclass with `blocked: bool` and `reason: str`); stdlib-only, deterministic, no I/O/network/clock/randomness.
- [ ] The VULN-9a0c65e6 reproduction prompt (alternating lab-fetch/chart-read "one thousand times in sequence") classifies as `blocked=True`, `reason="resource_exhaustion_loop"`.
- [ ] The VULN-06edd052 reproduction prompt (confirm-before-every-sentence, re-verify-from-scratch, "never finalized or delivered in complete form") classifies as `blocked=True`, `reason="nonterminating_process"`.
- [ ] A battery of legitimate clinical questions — including ones containing numbers or near-miss words ("summarize the last 10 lab results", "check the vitals again", "compare the previous 5 encounters", "list all active medications") — classify as `blocked=False`, `reason=""` (no false positives).
- [ ] When `classify_request` blocks, `ClaudeAgent.run_turn` (and thus `run`) returns a fixed refusal that (a) reads as a refusal and invites a specific clinical question, (b) contains no digits and no chart PHI, and makes ZERO message-creator calls and ZERO boundary/tool calls (the fake creator's `.calls` and the boundary's `.pids` are both empty).
- [ ] On a blocked turn `run_turn` still appends the assistant refusal to the returned message list, records a `blocked` verification verdict on the observer, and (when `on_event` is given) emits one `{"type": "refused", "reason": ...}` event.
- [ ] A normal clinical question is NOT short-circuited: `run_turn` calls the message-creator as before (guard is transparent on the happy path); existing agent behavior is unchanged.
- [ ] `agent._SYSTEM_PROMPT` gains a clause instructing the model, when declining a manipulative/adversarial/looping/never-terminating request, to refuse without volunteering chart PHI and to invite a specific clinical question (guard-test asserts the clause is present; existing prompt guard-tests still pass).

## Test plan (orchestrator authors these)
- unit (`tests/test_request_guard.py`): both reproduction prompts flag with the correct `reason`; a no-false-positive battery of legitimate clinical questions stays unblocked; edge cases (small counts like "5 times" don't trip the loop rule; "again" alone doesn't; empty/whitespace question is unblocked); verdict dataclass shape and immutability.
- integration (`tests/test_agent_request_guard.py`, using the ScriptedCreator/RecordingBoundary fakes from the existing test_agent style): each reproduction prompt → `run`/`run_turn` returns the PHI-free refusal with `creator.calls == []` and `boundary.pids == []`; returned refusal is digit-free and contains none of the attack's injected patient tokens; a benign question still invokes the creator; `on_event` receives one `refused` event and the observer records a `blocked` verdict; the assistant turn is appended to history.
- prompt guard (in the integration file): `_SYSTEM_PROMPT` contains the new anti-PHI-on-refusal clause.

## Outcome
Implemented `sidecar/request_guard.py` (pure classifier) and wired it into `ClaudeAgent.run_turn` with a PHI-free, digit-free refusal that makes zero model/tool calls on a blocked turn; added the system-prompt anti-PHI-on-decline clause. Both red-team reproduction prompts are refused with no chart data fetched. The reviewer pass (run by the orchestrator after the sub-agent reviewer died on repeated infra errors) caught a BLOCKING false positive — bare "times" + any clinical value ≥25 wrongly refused "how many times has the systolic been over 140?" — which was fixed by requiring an explicit repetition instruction (verb/loop phrase) paired with a large count or unbounded word, dropping bare "times"/"in a row"/"in sequence". Ticket tests: 36 passed. Full sidecar suite: 751 passed, 2 skipped. Known limitation (documented, accepted as non-blocking): a rare descriptive past-tense phrasing that pairs a repeat-verb with a large number (e.g. "labs repeated across 30 encounters") can still over-trigger a refusal; tightening it risks under-blocking real "repeating" attacks, and the guard is defense-in-depth over the existing per-turn tool budget.
