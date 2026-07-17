---
id: 059a
title: Week-2 dashboard panels — event + per-category eval aggregation
status: ready-for-merge
depends_on: []
branch: ticket/59a-week2-dashboard-panels
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_dashboard_panels.py tests/test_eval_by_category.py tests/test_dashboard_doc.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Build the Week-2 dashboard panels the architecture (§7) calls for, DERIVED from the already-emitted T57 structured events (`ingestion.*`, `extraction.field`, `retrieval.hit/miss`, `worker.handoff`, `eval.run`) rather than new infra. Add a pure `sidecar/panels.py` that aggregates a stream of event records into the five panel metrics: document-ingestion count, extraction field-level pass rate, RAG retrieval hit rate, supervisor routing-decision counts, and eval pass/fail per category. The per-category eval panel needs a real per-category breakdown that does not exist yet: `EvalResult` carries no category and `run_all` only aggregates overall pass/total — so add `category` to `EvalResult` and a `by_category` breakdown to the `run_all` summary (additive, backward-compatible). Document the panels in `DASHBOARD.md` (a Week-2 section mapping each panel to its backing event/field), guarded by a static-text test.

## Acceptance criteria
- [ ] `panels.aggregate_week2_events(events)` takes a list of event records (the dicts `events.log_event` returns / emits) and returns a dict with: `ingestion_count` (number of `ingestion.complete`), `extraction` (counts by `outcome` + `field_pass_rate` = ok / total `extraction.field`), `retrieval` (`hits`, `misses`, `hit_rate` = hits/(hits+misses)), and `routing` (counts of `worker.handoff` keyed by the `to` target). Empty input → zeros with rates defined as `0.0` (no divide-by-zero).
- [ ] Aggregation reads the REAL emitted field names (`event`, `outcome`, `count`, `from_`, `to`, `document_id`, `doc_type`) — cross-checked against the `log_event(...)` call sites in `graph.py`/`server.py`. Unknown/other event types are ignored, not errors.
- [ ] `EvalResult` gains a `category: str | None = None` field, populated from the case; `run_all`'s summary gains `by_category`: `{category: {"passed": int, "total": int, "pass_rate": float}}` covering every case's category (cases with no category grouped under a stable key e.g. `"uncategorized"`). Existing summary keys/behaviour and the existing eval tests are unchanged.
- [ ] `panels.eval_pass_fail_by_category(summary)` returns the per-category pass/fail view from a `run_all` summary (thin, reusing `by_category`).
- [ ] `DASHBOARD.md` has a Week-2 panels section naming all five panels and mapping each to its backing T57 event(s)/field(s); a static-text guard asserts their presence. Pure/deterministic: `panels.py` is stdlib-only, no network, no new deps.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_dashboard_panels.py` — feed a hand-built event stream (ingestion/extraction/retrieval/routing, incl. empty) through `aggregate_week2_events`; assert counts, rates, divide-by-zero safety, and that unrelated events are ignored. Include a round-trip using `events.log_event` return values so the panel reads the REAL record shape (contract, decision #12).
- `sidecar/tests/test_eval_by_category.py` — `run_all` over a tiny temp evals dir with categorised cases yields a correct `by_category` breakdown; `EvalResult.category` is populated; `eval_pass_fail_by_category` reflects it.
- `sidecar/tests/test_dashboard_doc.py` — static-text guard for the DASHBOARD.md Week-2 panels section.
