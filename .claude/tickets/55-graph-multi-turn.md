---
id: 055
title: Multi-turn / follow-up on the supervisor graph (reuse ConversationStore)
status: tests-authored
depends_on: []
branch: ticket/55-graph-multi-turn
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_graph_multi_turn.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Give the supervisor graph follow-up capability by threading conversation history through `run_supervisor`, reusing the existing pid-scoped, TTL-bounded `ConversationStore` (no new store, no persistence to disk). When a store + `conversation_id` are supplied, `run_supervisor` loads the prior turns, exposes them in the graph state (so the answer-composition seam / an injected finalizer can use them to resolve a follow-up like "is that normal?"), then appends this turn (user question + composed answer) and persists it. Without a store it stays exactly stateless (existing callers unchanged). pid-scoping and TTL expiry are inherited from `ConversationStore`, so one patient's context can never leak into another's follow-up.

## Acceptance criteria
- [ ] `GraphState` has an optional `history` channel (a list of prior `{role, content}` turns), seeded once and readable by the finalize seam; nodes never mutate it.
- [ ] `run_supervisor(..., store=None, conversation_id=None)` stays backward compatible: with no store it behaves exactly as today (stateless; `history` empty), and existing callers keep working.
- [ ] With a `ConversationStore` + non-empty `conversation_id`, `run_supervisor` loads prior history, seeds `state["history"]` with it, and an injected `finalizer` receives that prior history via the state.
- [ ] After the turn, the store holds the appended history — `[{role:user, content:question}, {role:assistant, content:answer}]` on turn 1, growing by two entries per turn — and the returned dict exposes the updated `history`.
- [ ] A second turn on the same `conversation_id` sees the first turn's messages as prior context (the follow-up seam works).
- [ ] pid isolation: a turn on the same `conversation_id` but a different `pid` sees NO prior history.
- [ ] TTL: once the store entry has expired, a follow-up on that `conversation_id` sees no prior history.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_graph_multi_turn.py` — load/persist round-trip through `ConversationStore`, finalizer-sees-prior-history, two-turn follow-up, pid isolation, TTL expiry, and stateless backward compatibility.
