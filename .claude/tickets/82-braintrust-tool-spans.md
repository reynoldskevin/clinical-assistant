---
id: 82
title: Emit per-tool Braintrust spans (tool executions / error rate / duration)
status: tests-authored
depends_on: []
branch: ticket/82-braintrust-tool-spans
base_branch: main
test_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest tests/test_tool_spans.py -q'"
full_suite_command: "docker exec w2-sidecar-test bash -lc 'cd /repo && python -m pytest -c sidecar/pytest.ini sidecar/tests'"
attempts: 0
---

## Description
The Braintrust monitor's built-in **Tool executions / Tool error rate / Tool duration** charts have no data, while everything else (turns, LLM latency via `wrap_anthropic`, outcomes, the `metrics.tool_calls` count) populates. Root cause: the sidecar never emits per-tool spans. The agent runs inside an `agent-turn` span and `wrap_anthropic` emits `llm`-type spans, but when a tool executes the agent only calls `observer.record_tool_call(name, ok)` (an in-process counter) — it never opens a Braintrust `type=tool` span, which is exactly what those built-in charts aggregate. This ticket emits a `type=tool` span per tool execution (name = tool name, duration = the handler call, error status from exception propagation), nested under the turn span, so the charts populate. Fully guarded: observability must never break the request path.

## Acceptance criteria
- [ ] AC1 — The tracer interface gains `tool_span(name)` returning a context manager: `NullTracer.tool_span` is a no-op (`nullcontext`); the Braintrust tracer's opens `braintrust.start_span(name=<tool>, type="tool")` (the `type="tool"` is what the built-in charts key on), guarded so a span failure degrades to a no-op and never raises.
- [ ] AC2 — `ClaudeAgent` accepts a `tracer` (default `NullTracer`) and wraps EACH tool execution — the built-in `get_patient_summary` boundary read AND every injected chart tool `handler(pid, input)` — in `with self._tracer.tool_span(<tool name>):`, so one tool span is opened per tool call.
- [ ] AC3 — A failing tool's exception propagates THROUGH the tool_span context (so Braintrust marks the span errored → tool error rate), and the agent still catches it outside the span and continues (no crash; the existing tool-error result is still fed back to the model).
- [ ] AC4 — A broken tracer (whose `tool_span` raises) never breaks the turn — the agent still produces its answer.
- [ ] AC5 — `default_agent_builder` passes the Braintrust tracer into `ClaudeAgent`; existing tests + full suite stay green.

## Test plan (orchestrator authors these; LOCKED)
- py (new `sidecar/tests/test_tool_spans.py`): a fake tracer records `tool_span` calls — the agent opens one per tool (summary + a generic tool), in order (AC2); a failing tool propagates the exception through its span (AC3) while the turn still completes; a tracer whose `tool_span` raises does not break the turn (AC4); and — via a fake `braintrust` module injected into `sys.modules` with `BRAINTRUST_API_KEY` set — `build_tracer().tool_span("x")` calls `braintrust.start_span(name="x", type="tool")` (AC1, the type contract) and `NullTracer.tool_span` is a no-op without a key.
