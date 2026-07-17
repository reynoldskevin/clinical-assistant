---
id: 059b
title: Week-2 alerts + per-category eval-regression + runbooks
status: done
depends_on: [059a]
branch: ticket/59b-week2-alerts-runbooks
base_branch: ticket/59a-week2-dashboard-panels
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_week2_alerts.py tests/test_week2_alerts_doc.py tests/test_alerts_doc.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Add the Week-2 alerts the architecture (§7/§10) calls for, on top of T59a's panel aggregation, and document each with an incident-response runbook in `ALERTS.md` (extending the existing five). Add a pure `sidecar/alerts.py` with the derivable alert logic: an extraction-failure-rate alert (fires when the `extraction.field` failure rate — non-`ok` outcomes — over a window exceeds a threshold), and a per-CATEGORY eval-regression detector (fires when any eval category's pass rate drops by MORE than 5% below a baseline — mirroring `ci_gate.regression_gate`'s `MAX_REGRESSION` semantics but keyed on category, consuming T59a's `by_category`). The RAG-retrieval-latency alert has no latency field in the event stream, so it is defined in `ALERTS.md` as a Braintrust/BTQL-style definition (like the existing Alert 1), with retrieval hit/miss rate from T59a as the derivable RAG-health complement. `ALERTS.md` gains three alert definitions (extraction-failure, RAG-retrieval latency, eval-regression) each with a runbook; a static-text guard asserts their presence. Stacked on T59a (imports `panels`).

## Acceptance criteria
- [ ] `alerts.evaluate_extraction_failure(panel_or_events, threshold, min_fields=...)` returns a firing decision (a small dict `{firing: bool, rate: float, ...}`): the extraction failure rate is `(unsupported + low_confidence) / total` `extraction.field` outcomes; fires iff `rate > threshold` AND there are at least `min_fields` observations (a volume floor to avoid noise). Below the floor → `firing=False`.
- [ ] `alerts.detect_eval_regression(baseline_by_category, current_by_category, max_regression=0.05)` returns the list (sorted) of categories whose pass rate dropped by STRICTLY MORE than `max_regression` below baseline; a drop of exactly `max_regression` is allowed (matches `ci_gate.MAX_REGRESSION` semantics). Categories absent from `current` are treated as a full drop; categories absent from `baseline` are ignored. Consumes the `by_category` shape T59a produces.
- [ ] Both functions are pure/deterministic (stdlib only, no network, no new deps) and JSON-serializable outputs; divide-by-zero safe.
- [ ] `ALERTS.md` gains three new alert sections — extraction-failure rate, RAG-retrieval latency, and eval-regression (>5% per category) — each with a threshold/definition AND an on-call **runbook** (what it means + numbered response steps), consistent with the existing Alert 1–5 style. A static-text guard asserts all three titles + a runbook marker per alert are present.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_week2_alerts.py` — `evaluate_extraction_failure` firing/not-firing across threshold + volume-floor boundaries; `detect_eval_regression` at the exact-5% boundary (allowed), >5% (regresses), missing-category (full drop), and baseline-only category (ignored). Feed `detect_eval_regression` the real `by_category` shape from a `run_all` summary (contract, decision #12).
- `sidecar/tests/test_alerts_doc.py` — static-text guard for the three new ALERTS.md sections + a runbook marker each.
