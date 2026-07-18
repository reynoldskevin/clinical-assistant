---
id: 80
title: Eval-gate hardening — real-agent regression canary (offline, key-free) + blocking live sweep
status: ready-for-merge
depends_on: []
branch: ticket/80-eval-gate-hardening
base_branch: main
test_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest tests/test_offline_agent_canary.py -q'"
full_suite_command: "docker exec w2-sidecar-test bash -lc 'cd /repo && python -m pytest -c sidecar/pytest.ini sidecar/tests'"
attempts: 0
---

## Description
Hardens the Week-2 eval/CI gate so an introduced regression reliably fails CI (the grading hard-gate: "we introduce a small regression and confirm your CI gate fails"). Two gaps were found empirically: (1) the blocking offline job (pytest) catches deterministic/logic regressions but a regression that UNWIRES a gate at the agent level, or a pure LLM-answer-quality regression, could slip; (2) the scored live sweep (`eval:live`) is `manual`/`allow_failure`, so a real-LLM quality regression never reds the pipeline. This ticket adds (A) a KEY-FREE offline **real-agent regression canary** that drives the actual `ClaudeAgent` end-to-end (scripted model + fake boundary) and asserts the verification/safety gates are wired (V1 fabricated-citation strip, V6 identifier block, V8 unsafe-action block all applied by `agent.run`, and a healthy grounded answer is NOT over-blocked) — so unwiring any gate fails the blocking offline job even though the gate's own unit tests still pass; and (B) makes `eval:live` **blocking when `ANTHROPIC_API_KEY` is configured** (auto-runs on MR/branch and `allow_failure: false`), while remaining manual/non-blocking with no key so normal keyless CI is unaffected.

## Acceptance criteria
- [ ] AC1 — A real-agent canary drives `ClaudeAgent.run(...)` (scripted `MessageCreator`, fake boundary; no SDK, no key) and asserts the SAFETY/GROUNDING gates are applied at the agent level: a fabricated `[Sn]` citation is stripped (V1); a raw SSN in the model's draft is blocked (V6, safe fallback shown); an unsafe action directive — even on the CITED path — is blocked (V8, read-only fallback); and a healthy grounded cited answer passes through UN-blocked with its drug name + `[S1]` intact (no over-block).
- [ ] AC2 — The canary runs inside the blocking `eval:offline` job (it lives under `sidecar/tests/`, which that job runs) and is fully deterministic/offline.
- [ ] AC3 — `.gitlab-ci.yml` `eval:live` gains a rule so that when `$ANTHROPIC_API_KEY` is present it runs automatically on merge-request and branch pipelines with `allow_failure: false` (blocking); with no key it stays manual/`allow_failure: true` (non-blocking) and no keyless pipeline is broken. The scored command remains `python -m eval --live --threshold 0.9` (exit 1 on regression).
- [ ] AC4 — The existing gate suite (`test_ci_gate.py`, `test_verification*.py`, golden-set) stays green; full sidecar suite passes.

## Test plan (orchestrator authors these; LOCKED)
- py (new `sidecar/tests/test_offline_agent_canary.py`): the four AC1 agent-level gate-wiring canaries + AC3 `.gitlab-ci.yml` YAML assertions (eval:live blocks when key present, stays non-blocking keyless, script unchanged). Verified to have TEETH by injecting a gate-unwiring regression (confirmed a canary fails, then reverted).
