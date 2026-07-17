---
id: 058a
title: Resilience primitives — circuit breaker + timeout/retry wrapper
status: todo
depends_on: []
branch: ticket/58a-resilience-primitives
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_resilience.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Foundational resilience layer for the sidecar's remote dependency calls (Qdrant in T58b, and reusable for any network backend). Add a pure, deterministic `sidecar/resilience.py` providing a `CircuitBreaker` (closed → open after N consecutive failures → half-open after a cooldown → closed on a probe success / re-open on a probe failure) and a `call_resilient(fn, *, timeout, retries, breaker, clock, sleep)` helper that enforces a per-call timeout, retries a bounded number of times, and consults/records outcomes on the breaker so a downstream outage fails fast instead of hammering a dead service. Time is injected (a `clock` callable + `sleep` callable) so the whole thing is deterministic and needs no wall-clock, threads, or network.

## Acceptance criteria
- [ ] `CircuitBreaker(fail_max, reset_timeout, clock)` starts **closed** and `allow()` returns `True`. After `fail_max` consecutive `record_failure()` calls it is **open** and `allow()` returns `False` until `reset_timeout` has elapsed on the injected `clock`; then `allow()` returns `True` (**half-open**).
- [ ] A `record_success()` in half-open (or closed) resets the failure count and closes the breaker; a `record_failure()` while half-open re-opens it and restarts the cooldown.
- [ ] `state` (or equivalent) reports `"closed" | "open" | "half_open"` for observability; the breaker never raises from `allow()/record_*`.
- [ ] `call_resilient(fn, *, timeout, retries, breaker=None, clock, sleep)` calls `fn()`, returning its result on success and recording a breaker success. On a raised exception it retries up to `retries` times (total attempts = retries + 1); exhausting them re-raises the last exception and records a breaker failure per failed attempt.
- [ ] When a `breaker` is supplied and it is **open** (`allow()` is False), `call_resilient` short-circuits with a `CircuitOpenError` (a defined exception) WITHOUT calling `fn` — fail fast.
- [ ] A `fn` that exceeds `timeout` (measured via the injected `clock` around a cooperative call, no real threads required) is treated as a failed attempt (raises a `TimeoutError`), counting toward retries and breaker failures.
- [ ] Pure/deterministic: no `time.sleep`, no sockets, no threads in the logic path — all time via injected `clock`/`sleep`; no new dependencies.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_resilience.py` — breaker lifecycle (closed→open→half_open→closed / re-open), `allow()` gating, `call_resilient` success/retry-then-success/retry-exhausted paths, open-breaker short-circuit (fn never called), timeout-as-failure, sleep-before-retry-only, and determinism via an injected fake clock.
