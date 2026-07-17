---
id: 057b
title: Distributed tracing — supervisor → worker child spans
status: tests-authored
depends_on: [057a]
branch: ticket/57b-worker-child-spans
base_branch: ticket/57a-structured-events
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_worker_spans.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Second half of T57. Add distributed tracing to the supervisor graph: each worker runs inside its own child span (`W2_ARCHITECTURE.md` §7 — "Supervisor span → worker child spans → extraction/retrieval sub-spans; a full Week-2 request trace is reconstructable from the correlation ID alone"). Extend the tracer with a `worker_span(name, correlation_id, kind, parent)` context manager (no-op on `NullTracer`, zero overhead), wire it into the graph's worker nodes, and pass an optional `tracer` into `build_supervisor_graph` (defaulting to the null tracer so existing callers are unchanged). Stacked on T57a because it edits the same graph worker nodes.

## Acceptance criteria
- [ ] `observability.NullTracer` exposes `worker_span(name, correlation_id, kind=None, parent="supervisor")` usable as a context manager (no-op, opens no real span).
- [ ] `build_supervisor_graph(..., tracer=None)` defaults to a null tracer; existing callers (no `tracer`) keep working with no behavior change.
- [ ] Running the graph opens one worker child span per routed worker, carrying the worker `name`, the turn's `correlation_id`, its `kind` (`extraction` for the intake worker, `evidence` for the evidence worker), and `parent="supervisor"`.
- [ ] Every span carries the same `correlation_id` as the turn (the trace is reconstructable from the correlation id alone).
- [ ] Each worker span is entered AND exited (closed) around the worker's tool call — a tool error does not leak an unclosed span.
- [ ] Emitting spans is additive: `routing_log`, `worker_results`, and the final answer are unchanged (full graph regression stays green).

## Test plan (orchestrator authors these)
- `sidecar/tests/test_worker_spans.py` — a recording tracer asserts one child span per worker with name/kind/correlation_id/parent, span open+close ordering, cid-reconstructability, and NullTracer no-op usability.
