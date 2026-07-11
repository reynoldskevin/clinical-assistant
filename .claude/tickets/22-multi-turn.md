---
id: 022
title: Multi-turn conversation state (ephemeral, pid-scoped, TTL) (+ multi-turn test)
status: ready-for-merge    # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [021]
branch: ticket/22-multi-turn
base_branch: ticket/21-tool-chaining   # STACKED off T21 (unmerged) — shares agent.py/server.py; see skill decision #2
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Let a clinician ask follow-up questions in the same session with context carried
across turns, without the sidecar becoming stateful long-term: an **ephemeral,
pid-scoped, TTL-bounded** conversation store keeps the message history for a short
window so "is that normal?" resolves against the prior answer, then expires.

## Design

- **`conversation.py` — `ConversationStore`** (in-memory, injected clock for tests):
  `remember(conversation_id, pid, messages)` and `history(conversation_id, pid)`.
  `history` returns the stored messages ONLY if the entry exists, is not past its
  TTL, and the pid matches — a conversation bound to one patient can never surface
  another patient's context (security), and expired/unknown ids return `None`.
- **`agent.py` — `run_turn(question, pid, history=None) -> (answer, messages)`**:
  the tool-use loop, but starting from `history` (or fresh) and returning the FULL
  updated message list so the next turn can continue. `run(question, pid) -> str`
  stays as `run_turn(question, pid)[0]` — T12/T17/T21 behaviour unchanged.
- **`server.py` — `process_ask(auth, raw_body, agent_builder, store=None)`**: when a
  `store` is supplied and the body carries a `conversation_id`, load the pid-scoped
  history, call `run_turn`, persist the updated history, and return the answer.
  Without a store (or conversation_id) it stays stateless via `run()` — so the locked
  `test_server.py` (3-arg calls) is unaffected. `main()` wires a `ConversationStore`.

Note: the eval harness is single-turn; the "multi-turn case" here is a behavioural
unit test (store + agent continuation + server round-trip), not a YAML eval case.

## Acceptance criteria
- [ ] `ConversationStore.remember`/`history` round-trip returns the stored messages.
- [ ] History past its TTL returns `None` (and the entry is evicted); unknown id returns `None`.
- [ ] History is pid-scoped: `history(cid, otherPid)` returns `None` — no cross-patient context leak.
- [ ] `run_turn` returns `(answer, messages)`; a second `run_turn` with the prior history makes the model see the earlier turn's messages (context carried). `run()` still returns a plain `str`.
- [ ] `process_ask` with a store + `conversation_id` carries context across two calls and persists it pid-scoped; without a store it is stateless (`run()` path) so `test_server.py` stays green.
- [ ] All prior sidecar + module tests still pass.
- [ ] **MR carries `Depends on: !<T21-MR>` — merge T21 first** (stacked).

## Test plan (LOCKED — authored)
- `test_conversation.py`: remember/history round-trip; TTL expiry + eviction; pid-scoping; unknown id.
- `test_multi_turn.py`: `run_turn` returns (answer, history); second turn carries prior context; `run()` still returns str; `process_ask` multi-turn round-trip (context + pid-scope) and stateless-without-store.
