---
id: 42
title: Load-test harness + captured CPU/memory/latency/throughput baselines
status: ready-for-merge
depends_on: []
branch: ticket/42-perf-baselines
base_branch: main
test_command: "python -m pytest sidecar/tests/test_loadtest.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
Deliverable: capture baseline infrastructure metrics (CPU, memory, request
latency, throughput) under load-test scenarios and include them so future
performance changes can be measured against them.

Build a dependency-free load-test harness (`sidecar/perf/loadtest.py`) that drives
a target endpoint at a given concurrency, measures latency percentiles + throughput
+ error rate, and samples the sidecar process's CPU%/RSS (via `ps`). Run it against
the sidecar under representative scenarios and record the numbers in `METRICS_WEEK1.md`.

## Acceptance criteria
- [ ] `sidecar/perf/loadtest.py`:
  - `percentile(sorted_values, q)` — nearest-rank percentile (q in [0,1]).
  - `summarize(latencies_ms, elapsed_s, errors)` -> dict with `requests`,
    `errors`, `error_rate`, `throughput_rps`, and `latency_ms`
    {`p50`,`p95`,`p99`,`min`,`max`,`mean`}. Empty input is safe (zeros, no crash).
  - `run_scenario(url, n, concurrency, method, headers, body)` — threaded HTTP
    driver returning (latencies_ms, elapsed_s, errors).
  - `sample_process(pid)` — CPU%/RSS(MB) via `ps`.
  - `main(argv)` CLI to run named scenarios and emit a summary.
- [ ] `METRICS_WEEK1.md`: records the captured baselines under the load scenarios
  (health throughput, readiness latency, agent-turn latency), each with latency
  p50/p95/p99, throughput (rps), error rate, and the sidecar process CPU%/RSS,
  plus the environment (machine, host) and the methodology to re-run.
- [ ] No behaviour regression (full sidecar suite green).

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_loadtest.py`
  - percentile on [1..100]: p50=50, p95=95, p99=99
  - summarize: structure + throughput + error_rate + percentiles + empty-safe
- guard: `sidecar/tests/test_baselines_doc.py`
  - METRICS_WEEK1.md exists and documents cpu, memory, latency, throughput
