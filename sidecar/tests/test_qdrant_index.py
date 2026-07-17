"""T58b acceptance tests (LOCKED) — Qdrant-backed VectorIndex + factory.

Migrates the dense store from the pure-Python ``InProcessVectorIndex`` to a real
Qdrant service, behind the existing ``VectorIndex`` Protocol and following the
same lazy-import-and-degrade contract as the Cohere backends:

  * ``QdrantVectorIndex`` upserts/searches via an INJECTED client (a thin adapter
    exposing ``upsert(ids, vectors)`` and ``query(vector, k) -> [(id, score)]``);
    the real ``qdrant_client`` SDK is imported lazily by the DEFAULT client
    factory, never at construction — so these tests need no SDK and no network.
  * Every remote call goes through T58a ``call_resilient`` (timeout + retry +
    a shared ``CircuitBreaker``): a dead Qdrant fails fast, not forever.
  * ``build_vector_index()`` returns Qdrant only when ``QDRANT_URL`` is set AND
    the SDK imports; otherwise it degrades to ``InProcessVectorIndex``.
  * ``build_index()`` sources its vector index from that factory, so the offline
    path is unchanged and deterministic.

Deterministic: injected fake client + fake clock; no SDK, no sockets.
"""
import sys
import types

import pytest

import retrieval
from resilience import CircuitBreaker, CircuitOpenError
from retrieval import (
    InProcessVectorIndex,
    QdrantVectorIndex,
    build_index,
    build_vector_index,
)


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _noop_sleep(_seconds: float) -> None:
    return None


class FakeQdrantClient:
    """A stand-in for the production Qdrant adapter.

    Records upserts and returns canned, ordered query results. Set ``fail=True``
    to make every remote call raise (drives the resilience path).
    """

    def __init__(self) -> None:
        self.upserts: list[tuple[list[int], list[list[float]]]] = []
        self.fail = False
        self.query_calls = 0

    def upsert(self, ids, vectors) -> None:
        if self.fail:
            raise RuntimeError("qdrant down")
        self.upserts.append((list(ids), [list(v) for v in vectors]))

    def query(self, vector, k):
        self.query_calls += 1
        if self.fail:
            raise RuntimeError("qdrant down")
        # canned ranking, best-first; truncated to k
        return [(1, 0.9), (0, 0.5), (2, 0.1)][: max(0, k)]


def _make_index(client, **kw):
    kw.setdefault("clock", FakeClock())
    kw.setdefault("sleep", _noop_sleep)
    return QdrantVectorIndex(
        "http://qdrant:6333", "guidelines", dim=3,
        client_factory=lambda: client, **kw
    )


# --- Protocol parity: add + search --------------------------------------------

def test_add_forwards_sequential_integer_ids_by_insertion_order():
    fake = FakeQdrantClient()
    idx = _make_index(fake)
    idx.add([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    idx.add([[0.0, 0.0, 1.0]])
    assert fake.upserts[0][0] == [0, 1]      # first batch -> ids 0,1
    assert fake.upserts[1][0] == [2]         # second batch continues at 2


def test_search_returns_the_protocol_shape_best_first():
    fake = FakeQdrantClient()
    idx = _make_index(fake)
    result = idx.search([1.0, 0.0, 0.0], k=2)
    assert result == [(1, 0.9), (0, 0.5)]
    # same (int, float) tuple shape InProcessVectorIndex.search returns
    assert all(isinstance(i, int) and isinstance(s, float) for i, s in result)


def test_construction_is_lazy_no_sdk_import_or_connection():
    # Default client_factory would import qdrant_client (absent here) and connect.
    # Constructing alone must do NEITHER — no exception is raised.
    idx = QdrantVectorIndex("http://nope:6333", "guidelines", dim=3)
    assert idx is not None                    # constructed without touching the SDK


# --- resilience: timeout / retry / circuit breaker ----------------------------

def test_remote_failure_retries_then_opens_breaker_then_short_circuits():
    fake = FakeQdrantClient()
    fake.fail = True
    clock = FakeClock()
    breaker = CircuitBreaker(fail_max=2, reset_timeout=30, clock=clock)
    idx = _make_index(fake, breaker=breaker, retries=1, timeout=5, clock=clock)

    # retries=1 -> 2 attempts, both raise -> 2 breaker failures == fail_max -> open
    with pytest.raises(RuntimeError):
        idx.search([1.0, 0.0, 0.0], k=1)
    assert breaker.state == "open"
    calls_before = fake.query_calls

    # breaker now open: the next call fails fast WITHOUT hitting the client
    with pytest.raises(CircuitOpenError):
        idx.search([1.0, 0.0, 0.0], k=1)
    assert fake.query_calls == calls_before   # client was not called again


def test_transient_failure_recovers_within_retries():
    fake = FakeQdrantClient()
    clock = FakeClock()
    # first attempt fails, second succeeds
    state = {"n": 0}
    real_query = fake.query

    def flaky_query(vector, k):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient")
        return real_query(vector, k)

    fake.query = flaky_query
    idx = _make_index(fake, retries=2, timeout=5, clock=clock)
    result = idx.search([1.0, 0.0, 0.0], k=1)
    assert result == [(1, 0.9)]
    assert state["n"] == 2                     # retried once, then succeeded


# --- build_vector_index factory: gate + degrade -------------------------------

def test_build_vector_index_is_inprocess_without_qdrant_url(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    assert isinstance(build_vector_index(), InProcessVectorIndex)


def test_build_vector_index_degrades_when_sdk_import_fails(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    # sys.modules[name] = None makes `import qdrant_client` raise ImportError
    monkeypatch.setitem(sys.modules, "qdrant_client", None)
    assert isinstance(build_vector_index(), InProcessVectorIndex)


def test_build_vector_index_returns_qdrant_when_configured(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    # make the presence-check import succeed with a stub module (no real SDK)
    monkeypatch.setitem(sys.modules, "qdrant_client", types.ModuleType("qdrant_client"))
    idx = build_vector_index()
    assert isinstance(idx, QdrantVectorIndex)


# --- build_index sources its vector index from the factory --------------------

def test_build_index_uses_the_factory_and_stays_inprocess_offline(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    index = build_index()
    assert isinstance(index.vector_index, InProcessVectorIndex)
    assert len(index.chunks) > 0               # committed corpus still built


def test_build_index_routes_vectors_through_a_configured_qdrant(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    fake = FakeQdrantClient()
    # Force the factory to hand build_index a QdrantVectorIndex backed by our fake.
    monkeypatch.setattr(
        retrieval,
        "build_vector_index",
        lambda *a, **k: _make_index(fake),
    )
    index = build_index()
    assert isinstance(index.vector_index, QdrantVectorIndex)
    # the corpus vectors were upserted to Qdrant (one or more batches, non-empty)
    assert fake.upserts
    total = sum(len(ids) for ids, _ in fake.upserts)
    assert total == len(index.chunks)
