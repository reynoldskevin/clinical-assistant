---
id: 025
title: SSE streaming — live status events + buffered, gated answer (verify/stream reconciliation)
status: ready-for-merge    # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [024]
branch: ticket/25-sse-streaming
base_branch: main          # T24 merged; branch off main
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests/test_streaming.py"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Stream the agent turn to the browser over Server-Sent Events so the UI feels
responsive, WITHOUT ever showing the clinician unverified clinical content. The
chosen reconciliation is **stream status, buffer answer**: progress/status events
(the agent working, each tool call) are streamed live as they happen, but the
answer TEXT is buffered until the turn completes, run through the verification
gate (T23/T24), and only the gated `rendered_answer` is streamed — so nothing the
gate would strip, demote, or block ever reaches the screen. Because the message
creator already returns a complete response, the gate stays exactly where it is
(operating on the full draft); T25 adds an event channel around it, not a change
to how answers are verified.

## Design

- **`agent.py` — an event callback on the turn.** Add an optional
  `on_event: Callable[[dict], None] | None = None` parameter to `run_turn` (and a
  convenience `stream_turn(question, pid, history=None, on_event=None)` alias if
  cleaner). During the loop, each time a tool executes, call
  `on_event({"type": "tool", "name": <tool>, "ok": <bool>})` (success/failure/
  unknown alike). The FINAL gated answer is NOT emitted through `on_event` — it is
  returned as today via `(answer, messages)`. So status flows live; the answer is
  buffered + gated before the caller streams it. `on_event=None` → byte-for-byte
  identical behaviour to today (all T21/T22/T23/T24 tests stay green). The gate is
  applied exactly once, on the complete draft, before the answer is returned —
  status events must NEVER carry answer text (no unverified-content leak).
- **`server.py` — an SSE streaming core.** Add a pure, socket-free generator
  `stream_ask(authorization, raw_body, agent_builder, store=None, tracer=None)
  -> Iterator[bytes]` that yields SSE frames:
  - auth/validation failures → a single `event: error` frame carrying the same
    `{status, error}` shape `process_ask` would return (401/400), then stop.
  - otherwise: a `event: status` frame (`{"stage": "start"}`), then one
    `event: tool` frame per tool execution (streamed live via the `on_event`
    hook), then EXACTLY ONE `event: answer` frame whose `data` is
    `{"answer": <gated answer>}`, then a terminal `event: done` frame.
  - an agent error after the stream starts → an `event: error` frame
    (`{"error": "the assistant is unavailable"}`) instead of the answer frame;
    never leak internal detail.
  - multi-turn: when a `conversation_id` + store are present, load history, run
    the turn, and persist the updated history AFTER the answer frame is produced
    (same semantics as `process_ask`). The observability span still wraps the run.
  - SSE frame format: `event: <name>\ndata: <json>\n\n` (utf-8 bytes).
- **`server.py` — HTTP wiring.** `do_POST` routes `/ask/stream` to the streaming
  generator: respond `200` with `Content-Type: text/event-stream`,
  `Cache-Control: no-cache`, `Connection: keep-alive`, CORS headers, then write
  each yielded frame and flush. `/ask` keeps the existing buffered JSON behaviour
  unchanged (back-compat). `make_handler` needs no new constructor args.
- **`agent-widget.js` — consume the stream.** POST to `/ask/stream` and read the
  SSE body incrementally: on `status`/`tool` events, update the live "thinking"
  line (e.g. show the spinner + a short "reading medications…" style note); on the
  `answer` event, render the gated answer (existing markdown/table/italics
  rendering); on `error`, show the friendly failure. Keep the current
  conversation_id + Enter-to-send behaviour. (Vanilla JS — no unit harness in this
  repo; verified by inspection + manual, consistent with the T16 widget.)

## Acceptance criteria
- [ ] `run_turn(..., on_event=cb)` calls `cb` once per tool execution with `{"type":"tool","name","ok"}`, in execution order; returns the SAME gated `(answer, messages)` as the non-streaming call.
- [ ] `on_event=None` (default) reproduces today's behaviour exactly — existing agent/server/verification tests stay green.
- [ ] No status/tool event carries the answer text (the answer is only ever delivered buffered + gated) — no unverified-content leak.
- [ ] `stream_ask` yields SSE `event:`/`data:` frames: a `status` start frame, a `tool` frame per tool call, then exactly one `answer` frame carrying the GATED answer, then `done`.
- [ ] The streamed answer is the gate's `rendered_answer` — a fabricated citation is stripped / a blocked draft is replaced BEFORE the answer frame is emitted (verify/stream reconciliation proven end-to-end).
- [ ] Ordering: at least one status/tool frame is emitted BEFORE the answer frame (status live, answer buffered).
- [ ] Auth/validation failure → a single `error` frame with the same status/shape `process_ask` returns; an agent error mid-stream → an `error` frame, never internal detail.
- [ ] Multi-turn over the stream persists the updated history (follow-up turns carry context); stateless stream does not.
- [ ] `/ask` JSON endpoint behaviour is unchanged; `/ask/stream` serves `text/event-stream`.
- [ ] All prior sidecar tests still pass.

## Test plan (LOCKED — orchestrator authors)
- `test_streaming.py`:
  - agent: `on_event` receives a tool event per execution in order; streamed answer == non-streaming answer; `on_event=None` unchanged; a status event never contains the answer text.
  - server `stream_ask`: frame sequence (status → tool(s) → answer → done); answer frame carries the gated answer (fabricated citation stripped); a tool frame precedes the answer frame; auth-missing → single error frame (401); bad body → error frame (400); agent raises → error frame (no leak); multi-turn persists history, stateless does not.
