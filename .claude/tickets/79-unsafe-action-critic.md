---
id: 79
title: Critic completion — reject unsafe action suggestions (V8) + read-only prompt stance
status: ready-for-merge
depends_on: []
branch: ticket/79-unsafe-action-critic
base_branch: main
test_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest tests/test_verification_action.py -q'"
full_suite_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest -q'"
attempts: 0
---

## Description
Completes the partially-covered stretch goal "a critic agent that rejects uncited claims OR unsafe action suggestions." The uncited-claims half is already done (VerificationGate V1/V2 + the blocking V3/V6/V7, and CitationGate demotion). The MISSING half is rejecting the agent's own **unsafe action suggestions** — prescriptive clinical directives the read-only Co-Pilot must never make ("Administer 10 units of insulin", "You should start warfarin 5 mg", "I recommend increasing the metformin dose", "Discontinue the lisinopril"). Today nothing blocks such a generated recommendation, and the system prompt has no read-only/advisory stance. This ticket adds a deterministic **V8 (BLOCKING) unsafe-action-suggestion check** to `VerificationGate` (analogous to V3/V6/V7: detect → block → replace the draft with a tailored safe fallback that declines to recommend clinical actions), and adds an explicit read-only/advisory clause to the system prompt so the model avoids emitting directives in the first place (defense in depth). The detector distinguishes prescriptive directives/recommendations from DESCRIPTIVE or historical chart facts and from proper refusals, so it never blocks legitimate factual answers. Deterministic, offline, stdlib-only — consistent with the existing gate.

## Acceptance criteria
- [ ] AC1 — `VerificationGate.verify()` blocks a draft that makes an unsafe clinical action suggestion: verdict `"blocked"`, a flag `{"code": "unsafe_action_suggestion", "action": "blocked"}`, and the rendered answer is a safe fallback that (a) does NOT contain the directive's content and (b) communicates it will not provide clinical recommendations (a tailored action fallback, e.g. mentions "recommend"/"read-only"/"clinical action").
- [ ] AC2 — Positive cases blocked: imperative directives ("Administer 10 units of insulin now.", "Discontinue the lisinopril and switch to losartan.") AND recommendation phrasings ("You should start the patient on warfarin 5 mg daily.", "I recommend increasing the metformin dose to 1000 mg.", "Consider prescribing a statin.").
- [ ] AC3 — Negative cases NOT blocked by V8 (no `unsafe_action_suggestion` flag / not `blocked` on this basis): descriptive state ("The patient is currently on warfarin 5 mg daily [S1]."), historical/passive fact ("Warfarin was discontinued in 2020 [S1]."), a numeric result ("The most recent HbA1c was 7.8% [S1]."), a plain refusal ("I can't help with that."), and a negated non-recommendation ("I don't make treatment recommendations; the clinician decides on any changes.").
- [ ] AC4 — Existing V1/V2/V3/V6/V7 behaviour is unchanged (their fallback still contains "verify"); the block precedence still holds. Full sidecar suite stays green.
- [ ] AC5 — `agent._SYSTEM_PROMPT` gains an explicit read-only/advisory clause instructing the model not to recommend/prescribe/order clinical actions (it surfaces chart facts for the clinician to act on).
- [ ] AC6 (agent integration) — when the model emits a directive final answer, `ClaudeAgent.run(...)` returns the safe fallback (directive content not shown), mirroring the V3 integration test.

## Test plan (orchestrator authors these; LOCKED)
- py (new `sidecar/tests/test_verification_action.py`): V8 positive blocks (AC1/AC2); V8 negatives not blocked (AC3); interaction/precedence (AC4); `_SYSTEM_PROMPT` read-only clause (AC5); scripted-creator agent integration blocks a directive answer (AC6). The existing `test_verification_constraints.py` (V3/V6/V7) is the regression guard for AC4 and must stay green untouched.
