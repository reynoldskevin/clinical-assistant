# AI Sidecar — Braintrust Dashboard Spec

This document specifies the observability dashboard for the read-only Clinical
Co-Pilot sidecar. All telemetry lands in the Braintrust project **`oe-ai-agent`**.

## Live dashboard (created via API)

A `monitor` view was created programmatically via the Braintrust REST API by
`sidecar/dashboard/create_dashboard.py` (idempotent — re-running reuses the
existing view). It renders the metrics below in real time:

- **Project** `oe-ai-agent` (org `KevinReynolds`)
- **Monitor view** — `45befea2-caef-467d-9303-52bc4a48857c`
- **URL** — <https://www.braintrust.dev/app/KevinReynolds/p/oe-ai-agent/monitor>
  (the app path uses the org + project *names*, not their ids)

The Braintrust **Monitor** tab auto-aggregates the logged spans/metrics (request
volume, latency percentiles, error rate, and any logged scores/metrics, sliceable
by metadata). The per-chart field mapping below documents which logged field backs
each required chart; add or pin charts in the Monitor UI using these fields.
Re-run the script any time with `python sidecar/dashboard/create_dashboard.py`.

## Data sources

Two layers feed the dashboard:

- **`wrap_anthropic` (auto-instrumented Claude calls).** Provides per-call
  **latency** and **token** counts (input/output) for every model round-trip.
  These roll up automatically under the agent-turn span.
- **The agent-turn span (`turn` span).** One span per `/ask` (or `/ask/stream`)
  request. It carries the **request count** (one span == one request) plus the
  per-turn metrics logged by `_log_span_metrics` in `server.py` via
  `span.log(metrics=, scores=, metadata=)`. These are aggregated from the
  agent's `TraceCollector.summary()` after the turn completes.

### Logged fields (per turn)

`span.log` records:

- `metrics`: `tool_calls`, `tool_failures`, `model_calls`, `input_tokens`,
  `output_tokens`, `cost_usd`, `retries`.
- `scores`: `success` (1.0 ok / 0.0 error) and, when a citations block was
  gated, `verification_pass` (`pass`→1.0, `pass_with_flags`→0.5,
  `blocked`→0.0).
- `metadata`: `outcome` (`ok`/`error`), `verification_verdict`, `truncated`,
  `degraded`, `correlation_id`.

## Required charts

| Chart | Source field | Notes |
|-------|--------------|-------|
| **Total requests** | count of `turn` spans | one span per request |
| **Error rate** | `scores.success` / `metadata.outcome` | `1 - mean(success)`; equivalently the fraction with `outcome == "error"` |
| **Latency (p50 / p95)** | `wrap_anthropic` span duration | end-to-end model + turn latency percentiles |
| **Tool call counts** | `metrics.tool_calls` | sum / distribution of tool calls per turn |
| **Retry counts** | `metrics.retries` | sum of retries; see note below |
| **Verification pass/fail rate** | `scores.verification_pass` | fraction of gated turns passing verification |

## Agent-specific charts

| Chart | Source field | Definition |
|-------|--------------|------------|
| **Cost per turn** | `metrics.cost_usd` | mean/distribution of USD cost per turn |
| **Gate-block rate** | `metadata.verification_verdict` | fraction of turns with `verification_verdict == "blocked"` |
| **Degraded rate** | `metadata.degraded` | fraction of turns where a record lookup failed |
| **Truncated rate** | `metadata.truncated` | fraction of turns that hit the tool-call budget |

## Week-2 panels

The Week-2 dashboard panels (`W2_ARCHITECTURE.md` §7) are **derived from the T57
structured events** (`sidecar/events.py`), not from new telemetry infra. Each
event record is one PHI-free JSON object joined by `correlation_id`;
`panels.aggregate_week2_events` folds a stream of them into the first four panel
metrics, and `panels.eval_pass_fail_by_category` reads the per-category rollup
off an `eval.run_all` summary. The mapping from panel to backing event/field:

| Panel | Source event/field | Definition |
|-------|--------------------|------------|
| **Document-ingestion count** | `ingestion.complete` | number of documents that finished ingestion |
| **Extraction field-level pass rate** | `extraction.field` (`outcome`) | fraction of extracted fields with `outcome == "ok"`, plus a per-outcome breakdown |
| **Retrieval hit rate** | `retrieval.hit` (vs `retrieval.miss`) | `hits / (hits + misses)` across RAG retrievals |
| **Supervisor routing decisions** | `worker.handoff` (`to`) | count of handoffs keyed by the routed-to worker |
| **Eval pass/fail per category** | `eval.run` → `run_all` summary `by_category` | passed / total / pass_rate grouped by case category |

All rates are divide-by-zero safe (`0.0` when the denominator is empty), and the
aggregation is a deterministic, pure-stdlib fold — no network, no new deps.

## Notes

- **`retries` is currently `0` by design.** The agent is fail-fast: transport-level
  retries are handled by the Anthropic SDK, not by the agent loop. The `retries`
  metric is logged now so the dashboard surfaces any future retry behaviour
  without a schema change.
- All metric logging is additive and guarded: a log-less/None span or a
  `span.log` error is a silent no-op, so telemetry never breaks a request.
