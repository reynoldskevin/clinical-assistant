"""T22 acceptance tests (LOCKED) — ConversationStore (ephemeral, pid-scoped, TTL).

Unit tests with an injected clock so TTL is deterministic. No network, no SDK.
"""
from conversation import ConversationStore


def _clock():
    """A mutable fake clock: returns t[0]; advance by mutating it."""
    t = [1000.0]
    return t, (lambda: t[0])


def test_remember_and_history_roundtrip():
    t, now = _clock()
    store = ConversationStore(ttl_seconds=600.0, clock=now)
    msgs = [{"role": "user", "content": "What is the BP?"}, {"role": "assistant", "content": "120/80"}]

    store.remember("c1", 42, msgs)

    assert store.history("c1", 42) == msgs


def test_history_expires_after_ttl_and_is_evicted():
    t, now = _clock()
    store = ConversationStore(ttl_seconds=600.0, clock=now)
    store.remember("c1", 42, [{"role": "user", "content": "hi"}])

    t[0] = 1000.0 + 601.0  # past the TTL
    assert store.history("c1", 42) is None
    # even if the clock rewinds, the expired entry was evicted (not resurrected)
    t[0] = 1000.0
    assert store.history("c1", 42) is None


def test_history_is_pid_scoped_no_cross_patient_leak():
    t, now = _clock()
    store = ConversationStore(ttl_seconds=600.0, clock=now)
    store.remember("c1", 42, [{"role": "user", "content": "patient 42 context"}])

    assert store.history("c1", 99) is None      # different patient -> no context
    assert store.history("c1", 42) is not None  # same patient -> context returned


def test_unknown_conversation_returns_none():
    _, now = _clock()
    store = ConversationStore(ttl_seconds=600.0, clock=now)
    assert store.history("does-not-exist", 42) is None


def test_history_returns_a_copy_not_the_internal_list():
    t, now = _clock()
    store = ConversationStore(ttl_seconds=600.0, clock=now)
    store.remember("c1", 42, [{"role": "user", "content": "hi"}])

    got = store.history("c1", 42)
    got.append({"role": "user", "content": "mutation"})
    # mutating the returned list must not corrupt the stored conversation
    assert len(store.history("c1", 42)) == 1
