---
id: 41
title: Alert definitions + on-call runbook on the Braintrust dashboard
status: ready-for-merge
depends_on: [38]
branch: ticket/41-alerts
base_branch: main
test_command: "python -m pytest sidecar/tests/test_alerts_doc.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
Deliverable: define at least three alerts on the dashboard — p95 latency,
error rate, tool failure rate — and document what each means + the on-call
response. Braintrust alerts are automations configured in the UI (no public
automation REST API — `/v1/automation` → 404), so this is a definition/runbook
artifact: `ALERTS.md` gives each alert's metric, BTQL condition, threshold,
window, meaning, and on-call response, mapped to the fields the sidecar logs to
Braintrust (T38), plus the UI setup steps.

## Acceptance criteria
- [x] `ALERTS.md` defines the three required alerts (p95 latency, error rate,
      tool failure rate) each with threshold + BTQL + window + severity.
- [x] Each alert documents "what it means" and an "on-call response" runbook.
- [x] Alerts map to the logged fields (scores.success, metrics.tool_calls/
      tool_failures, span duration) and note UI creation (no public API).
- [x] Guard test pins the doc content; full suite green.

## Test plan
- guard: `sidecar/tests/test_alerts_doc.py` — the three alerts, thresholds,
  on-call response, BTQL/metric mapping are present.
