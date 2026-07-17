"""T55 acceptance tests (LOCKED) — multi-turn / follow-up on the supervisor graph.

The graph is stateless per invocation; a follow-up ("is that normal?") needs the
prior turn. This ticket threads conversation history through `run_supervisor`,
reusing the existing pid-scoped, TTL-bounded `ConversationStore` — load the prior
turns, expose them to the answer-composition seam, then append + persist this
turn. Without a store the graph stays exactly stateless.

Deterministic: scripted graph tools + an injected finalizer that reports how much
prior history it saw; the store uses an injected clock for TTL. No live API.
"""
from conversation import ConversationStore
from graph import _INTAKE, run_supervisor


class _Tool:
    """A scripted graph leaf tool returning a fixed citation."""

    def __init__(self, ref):
        self._ref = ref

    def __call__(self, *, question, pid, correlation_id):
        return {"citations": [self._ref], "payload": {}}


def _extractor():
    return _Tool("intake:1")


def _retriever():
    return _Tool("[S1]")


def _prior_count_finalizer(state):
    """An answer that reports how many prior-history messages the turn saw."""
    return f"prior={len(state.get('history', []))}"


def _turn(question, pid, *, store=None, conversation_id=None, finalizer=None, cid="cid-mt"):
    return run_supervisor(
        question,
        pid,
        correlation_id=cid,
        extractor=_extractor(),
        retriever=_retriever(),
        finalizer=finalizer,
        store=store,
        conversation_id=conversation_id,
    )


# --- 1. backward compatibility: no store => stateless as before --------------

def test_run_supervisor_without_a_store_is_stateless():
    state = _turn("what meds is the patient on?", 1)
    assert "answer" in state and "worker_results" in state
    # No conversation carried; history (if present) is empty.
    assert state.get("history", []) == []


# --- 2. history channel is seeded and reaches the finalize seam --------------

def test_finalizer_sees_no_prior_history_on_the_first_turn():
    store = ConversationStore(clock=lambda: 0.0)
    state = _turn("q1", 1, store=store, conversation_id="c1", finalizer=_prior_count_finalizer)
    assert state["answer"] == "prior=0"


def test_second_turn_sees_the_first_turns_messages_as_prior_context():
    store = ConversationStore(clock=lambda: 0.0)
    _turn("q1", 1, store=store, conversation_id="c1", finalizer=_prior_count_finalizer)
    state2 = _turn("q2", 1, store=store, conversation_id="c1", finalizer=_prior_count_finalizer)
    # Turn 1 persisted two messages (user + assistant); turn 2 sees them.
    assert state2["answer"] == "prior=2"


# --- 3. load + persist round-trip through ConversationStore ------------------

def test_turn_is_appended_to_the_store_and_returned():
    store = ConversationStore(clock=lambda: 0.0)
    state = _turn("What are the meds?", 1, store=store, conversation_id="conv-A")
    persisted = store.history("conv-A", 1)
    assert persisted == [
        {"role": "user", "content": "What are the meds?"},
        {"role": "assistant", "content": state["answer"]},
    ]
    # The returned state exposes the updated history too.
    assert state["history"] == persisted


def test_history_grows_by_two_entries_per_turn():
    store = ConversationStore(clock=lambda: 0.0)
    _turn("q1", 7, store=store, conversation_id="c")
    _turn("q2", 7, store=store, conversation_id="c")
    third = _turn("q3", 7, store=store, conversation_id="c")
    assert len(store.history("c", 7)) == 6
    assert len(third["history"]) == 6


# --- 4. pid isolation --------------------------------------------------------

def test_a_different_pid_on_the_same_conversation_sees_no_prior_history():
    store = ConversationStore(clock=lambda: 0.0)
    _turn("q1", 1, store=store, conversation_id="shared", finalizer=_prior_count_finalizer)
    # Same conversation_id, different patient: must NOT inherit pid 1's history.
    other = _turn("q2", 2, store=store, conversation_id="shared", finalizer=_prior_count_finalizer)
    assert other["answer"] == "prior=0"


# --- 5. TTL expiry -----------------------------------------------------------

def test_expired_history_is_not_carried_into_a_follow_up():
    clock = {"t": 0.0}
    store = ConversationStore(ttl_seconds=100.0, clock=lambda: clock["t"])
    _turn("q1", 1, store=store, conversation_id="c", finalizer=_prior_count_finalizer)
    clock["t"] = 200.0  # past the TTL window
    state = _turn("q2", 1, store=store, conversation_id="c", finalizer=_prior_count_finalizer)
    assert state["answer"] == "prior=0"
