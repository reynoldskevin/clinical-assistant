---
id: 81
title: Make the live eval meaningful & reproducible (tool parity + eval JWT + seeded eval patient)
status: in-progress
depends_on: []
branch: ticket/81-live-eval-reproducible
base_branch: main
test_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest tests/test_eval_harness.py -q'"
full_suite_command: "docker exec w2-sidecar-test bash -lc 'cd /repo && python -m pytest -c sidecar/pytest.ini sidecar/tests'"
attempts: 0
---

## Description
The live eval sweep (`python -m eval --live`) scored ~0.68 on a healthy build, but the investigation showed that number is SPURIOUS: every chart read was 401ing (no eval JWT), the live runner wired only 4 of the 7 production tools (missing documents / get_intake_form / evidence_retriever), and the cases hard-code pids (42 empty, 1 repurposed as the AI demo) whose asserted data isn't present. The loose `contains_any`/`tool_used` graders then passed on the agent's tool-failure refusals. This ticket makes the live sweep actually measure agent quality, reproducibly and locally:
- (a) `build_live_runner` now wires the SAME tool set as `server.py` (encounter, results, medications, search, documents, get_intake_form, evidence_retriever) so it drives the production agent.
- (b) chart reads authenticate with a per-pid token minted from the shared signing key (`mint_eval_jwt`, stdlib HS256, matching ScopedTokenService) — an explicit `OE_AI_AGENT_EVAL_JWT` still overrides.
- (c) a deterministic, idempotent seed creates a dedicated EVAL PATIENT with exactly the data the cases assert (an anticoagulant incl. a stale-active warfarin row, an uncoded afib problem, an allergy, an encounter, NO HbA1c/INR, a wrong-chart intake form), committed as a re-runnable script.
- (d) the eval cases are repointed to the eval patient and graders tightened (add `no_tool_failures` so a broken boundary can no longer pass spuriously).

NOTE: this is a LOCAL / manual reproducible quality sweep, not a CI gate — `eval:live` stays non-blocking (the CI job stands up no OpenEMR backend). The deterministic offline gate remains the grading gate.

## Acceptance criteria
- [ ] AC1 — `build_live_runner` wires the same tool NAMES as `server.default_agent_builder` (parity test with fakes; no API key).
- [ ] AC2 — `mint_eval_jwt(pid, key)` produces a valid HS256 token (round-trip HMAC verify; correct `aud`/`pid`/`exp` claims) accepted by the boundary.
- [ ] AC3 — an idempotent seed script creates the eval patient with the asserted data; re-running it is a no-op-safe upsert.
- [ ] AC4 — the eval cases point at the eval patient and, run live against the seeded chart, the sweep scores >= 0.9 (documented run); graders reject tool-failure refusals (`no_tool_failures`).
- [ ] AC5 — offline suite stays green; a new `test_eval_harness.py` locks AC1/AC2 offline.

## Progress
- (a) tool parity + (b) `mint_eval_jwt` implemented in `sidecar/eval.py`; JWT smoke-tested against `read.php` → HTTP 200 (auth works). Diagnosing remaining data-gap failures to scope the seed (c).
