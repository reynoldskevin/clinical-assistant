---
id: 43
title: Load/stress test — 10 and 50 concurrent users against the deployed agent
status: ready-for-merge
depends_on: [42]
branch: ticket/43-stress-test
base_branch: main
test_command: "python -m pytest sidecar/tests/test_baselines_doc.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
Deliverable: run load tests simulating at least 10 and 50 concurrent users
against the DEPLOYED agent (`POST /ask` on the Railway sidecar), and record
p50/p95/p99 latency and error rate at each level.

Uses the T42 harness (`sidecar/perf/loadtest.py`) against the Railway deployment
with a dev-mint JWT. Results recorded in `METRICS_WEEK1.md`.

## Result (captured against Railway)
- **10 concurrent** (30 req): p50 5.8s · p95 8.1s · p99 11.5s · error rate 0%.
- **50 concurrent** (50 req): p50 8.9s · p95 13.0s · p99 15.5s · error rate 0%.
- Zero errors / no rate-limiting at either level; graceful latency degradation
  (~1.5x p50/p95 from 10→50). At 50 concurrent p95 crosses the 10s alert
  threshold (`ALERTS.md`) — the intended signal.

## Acceptance criteria
- [x] Load test at 10 and 50 concurrent users against the deployed `/ask`.
- [x] p50/p95/p99 latency + error rate recorded at each level in METRICS_WEEK1.md.
- [x] Guard test pins the concurrent-user stress section; full suite green.
