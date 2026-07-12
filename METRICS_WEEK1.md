# Week 1 Metrics — Performance Baselines (AI Clinical Co-Pilot sidecar)

Baseline infrastructure metrics (CPU, memory, request latency, throughput) for the
Python sidecar under representative load-test scenarios, captured as the **Week 1**
snapshot. These are the reference numbers **future performance changes are measured
against** — re-run the harness after a change and compare against this file (add
later snapshots as `METRICS_WEEK2.md`, etc.).

## How to reproduce

Harness: `sidecar/perf/loadtest.py` (standard-library only; nearest-rank
percentiles, throughput, error rate; samples the target process's CPU%/RSS via
`ps`). With the sidecar running (`python sidecar/server.py`):

```bash
PID=$(pgrep -f 'sidecar/server.py' | head -1)
# Scenario A — health throughput
python sidecar/perf/loadtest.py --url http://127.0.0.1:8900/health --n 2000 --concurrency 50 --pid $PID
# Scenario B — readiness latency (probes the 3 dependencies)
python sidecar/perf/loadtest.py --url http://127.0.0.1:8900/ready   --n 40   --concurrency 5  --pid $PID
# Scenario C — agent-turn latency (real LLM; needs a Bearer JWT)
python sidecar/perf/loadtest.py --url http://127.0.0.1:8900/ask --method POST \
  --header "Authorization: Bearer <jwt>" --header "Content-Type: application/json" \
  --body '{"pid":1,"question":"..."}' --n 6 --concurrency 2 --pid $PID
```

## Environment (baseline capture)

| | |
|---|---|
| Host | Apple `Mac17,9`, 15 logical cores, macOS 26.5 (arm64) |
| Runtime | Python 3.9.6 |
| Server | `ThreadingHTTPServer` (one thread per request) |
| Target | local sidecar `127.0.0.1:8900`; OpenEMR boundary on `localhost:8300`; Anthropic + Braintrust over the public internet |
| Captured | 2026-07 (local dev stack) |

> **Caveats.** These are **local dev-machine** baselines — treat them as the
> reference for this environment; production (Railway) infra metrics are read from
> the Railway service dashboard. `ps %cpu` is an average over the process lifetime,
> not an instantaneous peak, so it *under*-reports burst CPU — use it for
> trend/regression, not absolute capacity planning.

## Baselines

### Scenario A — health throughput (`GET /health`, no dependencies)

The sidecar's raw request-handling capacity — no external calls. This is the CPU/
memory/throughput baseline of the process itself.

| Metric | Baseline |
|---|---|
| Requests / errors | 2000 / 0 (0.0% error rate) |
| **Throughput** | **~5,470 req/s** |
| **Latency** | p50 **1.1 ms** · p95 **4.0 ms** · p99 **22 ms** · max 80 ms |
| **CPU** (process, peak) | ~13% of one core |
| **Memory** (RSS, peak) | ~15.5 MB |

### Scenario B — readiness latency (`GET /ready`, probes 3 dependencies)

Each request makes three external reachability checks (OpenEMR boundary, Anthropic,
Braintrust), so latency is dominated by network round-trips, not the sidecar.

| Metric | Baseline |
|---|---|
| Requests / errors | 40 / 0 (0.0% error rate) |
| Throughput | ~5 req/s (network-bound; not a capacity number) |
| **Latency** | p50 **937 ms** · p95 **1,190 ms** · p99 **1,555 ms** |
| CPU (process, peak) | ~9% of one core |
| Memory (RSS, peak) | ~23 MB |

### Scenario C — agent-turn latency (`POST /ask`, real LLM)

End-to-end agent turn (boundary read + tool loop + one or more Anthropic calls +
verification gate). Latency is dominated by the LLM call. Small sample (real API
cost); a latency baseline, not a throughput/capacity number.

| Metric | Baseline |
|---|---|
| Requests / errors | 6 / 0 (0.0% error rate) |
| Throughput | ~0.25 req/s at concurrency 2 (LLM-bound) |
| **Latency** | p50 **5.4 s** · p95 **12.5 s** · min 5.1 s · mean 7.4 s |
| CPU (process, peak) | ~8% of one core |
| Memory (RSS, peak) | ~46 MB |

## Reading these

- **Regression signals.** A change is a regression if, at the same scenario, it
  materially raises latency (esp. p95), lowers `/health` throughput, or raises the
  process RSS/CPU. Compare like-for-like on the same host.
- **Where time goes.** `/health` shows the process is cheap (µs–ms, ~5.5k rps);
  `/ready` and `/ask` latency lives almost entirely in the dependencies (network
  round-trips, and the multi-second LLM call). This is by design — the sidecar is
  thin and the LLM dominates, which is why the [dashboard](https://www.braintrust.dev/app/KevinReynolds/p/oe-ai-agent/monitor)
  and the [p95-latency alert](ALERTS.md) watch turn latency, not sidecar CPU.
- **Memory** grows from ~15 MB idle-ish (health) to ~46 MB on an agent turn
  (Anthropic client + per-turn buffers) — a useful RSS ceiling to watch.
