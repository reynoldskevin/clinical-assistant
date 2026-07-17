---
id: 073
title: GET /metrics endpoint — on-demand Week-2 telemetry snapshot
status: tests-authored
depends_on: []
branch: ticket/73-metrics-endpoint
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_metrics_buffer.py tests/test_metrics_route.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Add a `GET /metrics` endpoint to the sidecar — a sibling of `/health` and `/ready` that renders the Week-2 telemetry panels + derivable alerts on demand, so an operator or orchestrator can see live panel values without Braintrust. The T57 events are currently emitted-and-forgotten on the `sidecar.events` logger; add a bounded in-memory event buffer (a `logging.Handler` holding a `deque(maxlen=N)` of parsed event records, attached to the `sidecar.events` logger at server startup) and a `/metrics` handler that folds the buffered events through the merged `panels.aggregate_week2_events` and evaluates `alerts.evaluate_extraction_failure`, returning JSON. Unauthenticated and PHI-free like `/ready` (the events are ids/outcomes/counts by contract — no auth added). Reuse `panels.py`/`alerts.py` unchanged — no new aggregation logic. Out of scope (documented, not faked): the eval-regression alert (Alert 8) needs baseline-vs-current per-category across eval sweeps, not derivable from a live rolling buffer; RAG-latency (Alert 7) stays a Braintrust BTQL definition.

## Acceptance criteria
- [ ] New `sidecar/metrics_buffer.py`: a bounded `EventBuffer(maxlen=N)` — `add(record: dict)` appends and evicts oldest past `maxlen` (deque semantics); `snapshot()` returns an ISOLATED copy (mutating it or adding to the buffer afterwards does not change a prior snapshot); `__len__` and a `maxlen` attribute. Plus an `EventBufferHandler(logging.Handler)` whose `emit` parses each record's message as JSON and `add`s it, silently IGNORING non-JSON messages (no raise). Plus `install_event_buffer(maxlen=...) -> EventBuffer` that attaches the handler to the `sidecar.events` logger (removing any prior `EventBufferHandler` so repeated installs don't stack) and returns the buffer.
- [ ] `make_handler(...)` gains an optional `event_buffer: EventBuffer | None = None` param; `GET /metrics` returns HTTP 200 with body `{"panels": aggregate_week2_events(snapshot), "alerts": {"extraction_failure": evaluate_extraction_failure(panels, threshold, min_fields)}, "window": {"events": <len>, "buffer_max": <maxlen>}}`. When no buffer is wired, it behaves as an empty buffer (zeros, `firing=False`, still 200) — never a 500.
- [ ] The extraction-failure thresholds are the ALERTS.md Alert 6 starting points (failure-rate threshold `0.20`, volume floor `min_fields = 5`); a high non-`ok` extraction rate over the floor reports `firing=True`, a low rate or empty buffer `firing=False`.
- [ ] `/metrics` is UNAUTHENTICATED (no bearer required, like `/ready`) and returns only PHI-free aggregates. The endpoint is additive — `/health`, `/ready`, `/ask`, `/ask/stream`, `/extract` behaviour is unchanged.
- [ ] `main()` (server startup) installs the buffer via `install_event_buffer(...)` and passes it into `make_handler` so the live process's `/metrics` reflects real emitted events. Buffer size is a sensible default (e.g. 1000), overridable by env.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_metrics_buffer.py` — `EventBuffer` append/eviction at `maxlen`, snapshot isolation, `__len__`; `EventBufferHandler` parses JSON records / ignores non-JSON; `install_event_buffer` captures a REAL `events.log_event` emission (producer→buffer round-trip).
- `sidecar/tests/test_metrics_route.py` — boot the real `make_handler` on a loopback port (mirror `test_extract_route.py`) with a buffer populated from REAL `events.log_event` records; `GET /metrics` → 200 with the exact panels/alerts/window shape (contract, decision #12); empty buffer → zeros + not firing; a high extraction-failure rate → `firing=True`; unauthenticated GET still 200.
