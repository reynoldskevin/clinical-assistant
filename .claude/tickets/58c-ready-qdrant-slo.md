---
id: 058c
title: /ready Qdrant dependency probe + SLO / resilience baseline numbers
status: done
depends_on: []
branch: ticket/58c-ready-qdrant-slo
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_ready_qdrant.py tests/test_resilience_doc.py tests/test_architecture_doc.py tests/test_health_ready.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Close out T58's operability surface: make `/ready` actually probe Qdrant (the new dense-store dependency from T58b) and pin concrete SLO / resilience numbers in the architecture doc. Extend `health.build_readiness_checks` with a `qdrant` check that reports reachable/unreachable using the same injected-opener contract as the existing openemr/llm/observability checks, and — like `observability` — reports `not_configured` (a `None` ok that does NOT fail readiness) when `QDRANT_URL` is unset, so the offline/demo deploy stays ready. Wire the check into the `/ready` handler in `server.py`. Then record the timeout/retry/circuit-breaker budget and the dependency-probe behaviour as concrete numbers in `W2_ARCHITECTURE.md` §7 (SLOs) and §10 (failure modes). This ticket does not import T58a/b code, so it branches off `main`.

## Acceptance criteria
- [ ] `build_readiness_checks(...)` gains a `qdrant` dependency check keyed `"qdrant"`; when `QDRANT_URL` is configured it probes reachability via the injected opener (a 4xx/5xx answer counts as reachable, a connection failure as down), and when unset returns `(None, "not_configured")` so it does NOT fail readiness (mirrors `observability`).
- [ ] `ready_response(...)`/`evaluate_readiness` include the qdrant check result under `checks["qdrant"]`; an unreachable configured Qdrant yields HTTP 503, an unset one keeps 200, and all existing openemr/llm/observability behaviour is unchanged.
- [ ] The `/ready` handler in `server.py` passes the Qdrant URL (from `QDRANT_URL`, or its health endpoint) through to the readiness checks.
- [ ] `W2_ARCHITECTURE.md` §7 states the concrete per-dependency resilience budget (Qdrant call timeout, retry count, circuit-breaker fail-threshold + reset cooldown) as real numbers, and §10 documents the fail-fast/degrade behaviour when Qdrant is down (breaker opens → retrieval degrades, sidecar stays live). The existing §7 p95 guard still passes.
- [ ] No behavioural change when `QDRANT_URL` is unset (the default demo/offline deploy): `/ready` still returns 200 with `qdrant` reported `not_configured`.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_ready_qdrant.py` — extend the injected-opener style of `test_health_ready.py`: qdrant present in the checks; configured+reachable ⇒ ok True; configured+unreachable ⇒ 503; unset ⇒ ok None / `not_configured` and overall 200; openemr/llm/observability unaffected.
- `sidecar/tests/test_resilience_doc.py` — new doc guard: §7 states the concrete Qdrant resilience budget (2 s timeout, 2 retries, breaker opens after 5 consecutive failures, 30 s reset cooldown); §10 documents fail-fast/degrade (breaker opens → retrieval degrades, sidecar stays live).
- `sidecar/tests/test_architecture_doc.py` + `test_health_ready.py` are the LOCKED existing guards — they must stay green (regression).
