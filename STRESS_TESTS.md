# Load / Stress Tests — concurrent users against the DEPLOYED agent

Load tests of the **deployed** agent (`POST /ask` on the Railway sidecar
`ai-sidecar-production-c492.up.railway.app`, backed by the Railway OpenEMR
boundary + Anthropic) at increasing concurrency. Each request is a real
end-to-end agent turn (boundary read + tool loop + LLM call + verification gate).
Harness: `sidecar/perf/loadtest.py` (see `METRICS_WEEK1.md` for the single-user
baselines); JWT minted via the dev-mint endpoint on the synthetic demo.

## Results

| Concurrent users | Requests | **p50** | **p95** | **p99** | min / mean / max | Throughput | **Error rate** |
|---|---|---|---|---|---|---|---|
| **10** | 30 | **5.8 s** | **8.1 s** | **11.5 s** | 4.3 / 6.1 / 11.5 s | ~1.3 req/s | **0 %** (0/30) |
| **50** | 50 | **8.9 s** | **13.0 s** | **15.5 s** | 4.8 / 8.8 / 15.5 s | ~3.2 req/s | **0 %** (0/50) |

## Findings

- **Zero errors at both levels** — the deployed agent served 30 requests at 10
  concurrent and 50 requests at 50 concurrent with no failures and no
  rate-limiting (Anthropic and the boundary absorbed the concurrency).
- **Graceful latency degradation under load** — from 10→50 concurrent, p50 rose
  5.8 s → 8.9 s and p95 8.1 s → 13.0 s (~1.5×). The turn is LLM-dominated, so under
  concurrency the added latency is queueing/contention at the provider, not the
  thin sidecar. Aggregate throughput rose (1.3 → 3.2 req/s) as more turns ran in
  flight.
- **Relative to the p95-latency alert** (`ALERTS.md`, p95 > 10 s): a single-user
  turn (~5–6 s) is comfortably under, but **at 50 concurrent p95 (13 s) crosses
  the threshold** — i.e. sustained 50-concurrent load would legitimately fire that
  alert, which is the intended signal that the real-time budget is at risk under
  that load.

## Reproduce

_Captured 2026-07 against the Railway deployment. Mint a JWT (dev-mint), then:_

```bash
python sidecar/perf/loadtest.py --url <sidecar>/ask --method POST \
  --header "Authorization: Bearer <jwt>" --header "Content-Type: application/json" \
  --body '{"pid":1,"question":"…"}' --n <n> --concurrency <10|50>
```
