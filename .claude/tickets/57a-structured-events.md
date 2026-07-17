---
id: 057a
title: Week-2 structured log events (event spine + emission wiring)
status: done
depends_on: []
branch: ticket/57a-structured-events
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_events.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
First half of T57. Add the Week-2 structured-event spine (`sidecar/events.py`) that `W2_ARCHITECTURE.md` §7 describes — PHI-free event records searchable by `correlation_id`, emitted on a dedicated `sidecar.events` logger — and wire the emission points that already carry a correlation id: the graph's supervisor/worker handoffs (`worker.handoff`), the evidence worker (`retrieval.hit` / `retrieval.miss`), the intake worker's per-field outcomes (`extraction.field`, outcome only — never the value), the `/extract` flow (`ingestion.start` / `ingestion.complete`), and the eval sweep (`eval.run`). Distributed tracing / worker child spans are T57b.

## Acceptance criteria
- [ ] `sidecar/events.py` declares the seven Week-2 event types (`ingestion.start`, `ingestion.complete`, `extraction.field`, `retrieval.hit`, `retrieval.miss`, `worker.handoff`, `eval.run`) as constants + a `WEEK2_EVENTS` set, and `log_event(event, correlation_id, **fields)` that emits a structured JSON record on the `sidecar.events` logger and returns the record dict. An unknown event type raises `ValueError`.
- [ ] Emitted events are PHI-free by construction (a normal event carries ids/outcomes, never values; `phi_scan.find_identifiers` over the emitted log is clean).
- [ ] Running the graph emits a `worker.handoff` event per hop (carrying `correlation_id`, `from_`, `to`), one per `routing_log` entry.
- [ ] The evidence worker emits `retrieval.hit` (with a count) when it returns ≥1 citation, else `retrieval.miss`.
- [ ] The intake worker emits one `extraction.field` event per field outcome (`{field, outcome}`) from the tool payload's `field_outcomes`, never the extracted value.
- [ ] `default_extract_builder`'s extract fn emits `ingestion.start` and `ingestion.complete` (with `correlation_id` + `document_id`) bracketing the extraction.
- [ ] `eval.run_all` emits a single `eval.run` event carrying the sweep's `passed`/`total`.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_events.py` — event-spine unit tests + emission wiring across the graph, `/extract`, and the eval sweep, plus a PHI-free assertion via `phi_scan`.
