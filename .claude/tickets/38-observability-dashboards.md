---
id: 38
title: Instrument per-turn dashboard metrics onto the Braintrust span + spec
status: todo
depends_on: []
branch: ticket/38-observability-dashboards
base_branch: main
test_command: "python -m pytest sidecar/tests/test_dashboard_metrics.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description
Deliverable: a real-time dashboard (Braintrust) showing total requests, error
rate, p50/p95 latency, tool call counts, retry counts, verification pass/fail
rate — plus agent-specific metrics. `wrap_anthropic` already gives latency +
tokens, and the agent-turn span gives request count; but the collector's metrics
are only written to the sidecar log (not the span), the verification verdict is
discarded, and there is no outcome/degraded/truncated/retry signal. Attach the
full per-turn metric set to the Braintrust span so a dashboard can aggregate it,
and document the dashboard.

## Acceptance criteria
- [ ] `TraceCollector` gains `record_verification(verdict)`, `record_truncated()`,
      `record_degraded()`, `record_retry()`; `summary()` adds
      `verification_verdict` (str|None), `truncated` (bool), `degraded` (bool),
      `retries` (int). `NullObserver` gets matching no-ops.
- [ ] The agent records the verification verdict (from the gate) and records
      truncated/degraded when it appends those disclosures, so the observer
      summary reflects them.
- [ ] `process_ask` and `stream_ask` capture the span object and, after the turn,
      call `span.log(...)` with numeric `metrics` (tool_calls, tool_failures,
      model_calls, tokens, cost_usd, retries), `scores` (success 1/0;
      verification_pass 1/0.5/0 from the verdict, omitted when ungated), and
      `metadata` (outcome, verification_verdict, truncated, degraded,
      correlation_id). Guarded: a None/log-less span (NullTracer) is a no-op and
      never breaks the request.
- [ ] Error path logs `success=0` / outcome=error on the span when available.
- [ ] `sidecar/DASHBOARD.md` documents the Braintrust dashboard: the six required
      charts (total requests, error rate, p50/p95 latency, tool call counts,
      retry counts, verification pass/fail rate) mapped to the logged fields, plus
      agent-specific metrics (cost/turn, gate-block rate, degraded/truncated
      rate), and notes retries are 0 by design (fail-fast; SDK handles transport).
- [ ] `sidecar/dashboard/create_dashboard.py` — a best-effort script that uses the
      Braintrust REST API (raw HTTP + BRAINTRUST_API_KEY) to resolve the project
      and create/ensure a saved monitor view. Attempt it live; report honestly
      what the API accepted (Phase 2, run outside the TDD loop; not a blocking
      unit test since it needs live Braintrust).
- [ ] No behaviour regression (full sidecar suite green); telemetry never breaks
      the request.

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_dashboard_metrics.py`
  - TraceCollector new methods + summary fields
  - the gate's verdict is recorded on the observer through a run
  - run_turn records truncated (budget spent) and degraded (tool failure)
  - process_ask logs metrics+scores+metadata to a recording span
  - stream_ask logs metrics to a recording span
  - a NullTracer/log-less span never breaks the request
  - DASHBOARD.md exists and names the required metrics
