---
id: obs-1
title: Tag Braintrust with conversation_id + pid (group multi-turn conversations)
status: tests-authored     # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [022]
branch: feat/braintrust-conversation-metadata
base_branch: main          # T22 merged; branch off main
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Braintrust currently auto-logs each Claude call (via `wrap_anthropic`) but with no
`conversation_id` or `pid` — so multi-turn turns scatter as ungrouped, untagged
spans and you can't tell which calls belong to the same conversation or patient.
Wrap each agent turn in a Braintrust span tagged with `{conversation_id, pid}` so
the model calls nest under it and the UI can group/filter by conversation + patient.
Optional and guarded (only when `BRAINTRUST_API_KEY` is set); observability must
never break the request path.

## Design

- **`observability.py` — `NullTracer`**: `turn(metadata: dict)` returns a no-op
  context manager (the default; zero overhead, no braintrust import).
- **`factory.py` — `build_tracer()`**: returns a `NullTracer` unless
  `BRAINTRUST_API_KEY` is set, in which case it returns a Braintrust-backed tracer
  whose `turn(metadata)` opens a `braintrust` span carrying that metadata (so the
  `wrap_anthropic` calls nest under it). Fully guarded (import/runtime errors →
  fall back to a no-op), mirroring the existing braintrust wiring.
- **`server.py` — `process_ask(auth, raw_body, agent_builder, store=None, tracer=None)`**:
  wrap the agent call in `tracer.turn({"conversation_id": ..., "pid": ...})`, for both
  the stateless and multi-turn paths. The wrapping is SAFE — a failing tracer never
  breaks the request. `main()` wires `build_tracer()` through. `tracer=None` → NullTracer,
  so the locked `test_server.py`/`test_multi_turn.py` (no-tracer calls) are unaffected.

## Acceptance criteria
- [ ] `NullTracer().turn({...})` is a working no-op context manager.
- [ ] `process_ask` wraps the turn with `tracer.turn(metadata)` where metadata carries `pid` (both paths) and `conversation_id` (multi-turn); returns the answer unchanged.
- [ ] A tracer whose `turn()` raises does NOT break the request — `process_ask` still returns the answer (observability never breaks the request path).
- [ ] `build_tracer()` returns a no-op tracer when `BRAINTRUST_API_KEY` is unset, and falls back to no-op (no raise) when the key is set but braintrust is unavailable.
- [ ] Default `tracer=None` keeps `test_server.py`/`test_multi_turn.py` (no-tracer) green.
- [ ] All prior sidecar tests still pass.

## Test plan (LOCKED — authored)
- `test_tracer.py`: NullTracer no-op; process_ask tags pid (single-turn) + conversation_id (multi-turn); a failing tracer never breaks the request; build_tracer is a safe no-op without the key / without the lib.
