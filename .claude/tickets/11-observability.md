---
id: 11
title: Observability spine — traces, tokens/cost, tool-failures
status: ready-for-merge
depends_on: [12]
branch: ticket/11-observability
base_branch: ticket/12-sidecar
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests/test_observability.py"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description
Instrument the sidecar agent: record each model response's token usage (and compute
cost from model pricing), and each tool call's success/failure. Also make tool calls
fail-safe — a boundary error becomes an `is_error` tool_result the model can react to,
recorded as a failure, rather than crashing the turn.

## Acceptance criteria
- [ ] `sidecar/observability.py`: `NullObserver` (no-op) and `TraceCollector(model='claude-opus-4-8')`,
      both exposing `record_model_response(input_tokens: int, output_tokens: int)` and
      `record_tool_call(name: str, ok: bool)`.
- [ ] `TraceCollector.summary()` returns `model_calls`, `input_tokens`, `output_tokens`,
      `cost_usd` (from per-MTok pricing; claude-opus-4-8 = $5 in / $25 out), `tool_calls`, `tool_failures`.
- [ ] `ClaudeAgent` gains an optional `observer` (defaults to `NullObserver`): it calls
      `record_model_response` for every model response (0/0 when usage is absent) and
      `record_tool_call(name, ok)` for every tool call.
- [ ] Tool-failure recovery: a boundary exception is caught → `record_tool_call(..., ok=False)`
      + a `tool_result` with `is_error: True`; the turn continues (no crash).
- [ ] T12's existing tests still pass (observer defaults; usage-absent handled).

## Test plan (orchestrator authors these — LOCKED)
- unit (`sidecar/tests/test_observability.py`, spy/real TraceCollector + fakes): tokens +
  cost + tool_calls tallied across a turn; a boundary failure is recorded and the agent
  recovers (is_error fed back, final answer returned); NullObserver is the default;
  no-usage responses cost 0 but still count as a model call.

## Notes
Cost is derived, not measured — the pricing table is the single source. Real telemetry
export (OTel/logs) is out of scope; this is the in-process trace the sidecar emits.
