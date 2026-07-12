---
id: 35
title: Correlation ID — generate per agent invocation; log, trace, forward
status: ready-for-merge
depends_on: []
branch: ticket/35-correlation-id-sidecar
base_branch: main
test_command: "python -m pytest sidecar/tests/test_correlation_id.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 2
---

## Description
Deliverable: every agent invocation carries a unique correlation ID (CID) that
appears in every log entry, tool call, and LLM interaction so a full trace can be
reconstructed from logs alone. Nothing carries a CID today.

Sidecar half (PHP boundary audit-logging of the forwarded header is T36):
generate a unique CID per invocation, expose it on the agent, include it in every
sidecar log line and the observability trace/span, forward it as an
`X-Correlation-ID` header on every boundary tool call, and return it to the caller.

Design (minimal ripple): the CID is generated inside `default_agent_builder.build`
and passed to the boundaries + the `ClaudeAgent` (exposed via `.correlation_id`),
so `AgentBuilder`'s `(pid, jwt)` signature is unchanged and fake agents fall back
gracefully.

## Acceptance criteria
- [ ] `factory.new_correlation_id()` returns a unique non-empty id each call.
- [ ] `build_boundary(...)` and the chart boundary accept an optional
      `correlation_id`; when set, every boundary HTTP request carries an
      `X-Correlation-ID` header equal to it; when unset, no such header is sent.
- [ ] `ClaudeAgent` accepts and exposes `correlation_id`.
- [ ] `default_agent_builder.build` generates a CID, passes it to the boundaries
      and the agent; two builds get different CIDs.
- [ ] `process_ask` includes the CID in the returned body (`correlation_id`) and
      in its per-turn log line; `do_POST` sets an `X-Correlation-ID` response
      header for `/ask`. The CID is added to the tracer/span `metadata`.
- [ ] `stream_ask` logs the CID and emits it to the client (e.g. in the `done`
      frame).
- [ ] No behaviour regression (full sidecar suite green).

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_correlation_id.py`
  - new_correlation_id uniqueness/non-empty
  - build_boundary forwards X-Correlation-ID when set; omits when None
  - chart boundary forwards X-Correlation-ID
  - ClaudeAgent exposes correlation_id
  - default_agent_builder assigns a unique CID per build
  - process_ask returns + logs the CID
  - stream_ask emits + logs the CID
