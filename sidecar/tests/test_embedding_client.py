"""Tests for the real dense embedding backend behind the stub interface.

``build_embedding_client`` mirrors ``build_reranker``: a real Cohere embedder
when ``COHERE_API_KEY`` is set and the SDK imports, else the deterministic
``StubEmbeddingClient``. Everything here runs offline — the live Cohere call is
exercised only by a guarded smoke test that skips without a key. Constructing
``CohereEmbeddingClient`` must never import the SDK or touch the network.
"""

import os

import pytest

import retrieval
from retrieval import (
    CohereEmbeddingClient,
    StubEmbeddingClient,
    build_embedding_client,
    build_index,
    hybrid_retrieve,
)


# --- factory: guarded, offline-safe -------------------------------------------

def test_build_embedding_client_falls_back_to_stub_without_a_key(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    embedder = build_embedding_client()
    # Without a key we get the deterministic offline stub, not a Cohere client.
    assert isinstance(embedder, StubEmbeddingClient)
    vecs = embedder.embed(["alpha beta", "gamma"])
    assert vecs == embedder.embed(["alpha beta", "gamma"])  # deterministic
    assert len({len(v) for v in vecs}) == 1  # uniform dimensionality


def test_cohere_embedding_client_does_not_require_the_sdk_at_import_time():
    # Constructing the class must not import cohere (lazy). Instantiation is
    # cheap; only .embed() would touch the network — covered by the smoke test.
    e = CohereEmbeddingClient(api_key="unused-in-this-test")
    assert hasattr(e, "embed")


def test_cohere_embedding_client_returns_empty_for_no_texts():
    # An empty batch short-circuits before any SDK import or network call.
    assert CohereEmbeddingClient(api_key="unused").embed([]) == []


def test_get_guideline_index_uses_the_built_embedding_client(monkeypatch):
    # The production singleton must route its embedder through
    # build_embedding_client() so a configured key selects the real backend.
    retrieval._GUIDELINE_INDEX = None

    sentinel = StubEmbeddingClient()
    monkeypatch.setattr(retrieval, "build_embedding_client", lambda: sentinel)
    try:
        index = retrieval.get_guideline_index()
        assert index.embedding_client is sentinel
    finally:
        retrieval._GUIDELINE_INDEX = None


# --- live Cohere embeddings: guarded smoke test -------------------------------

@pytest.mark.skipif(
    not os.environ.get("COHERE_API_KEY"),
    reason="live Cohere smoke test — needs COHERE_API_KEY",
)
def test_cohere_embed_live_smoke():
    embedder = build_embedding_client()
    assert isinstance(embedder, CohereEmbeddingClient)
    # Real embeddings feed the same in-process cosine index; retrieval still
    # returns top-k cited chunks and surfaces the warfarin guidance.
    index = build_index(embedding_client=embedder)
    vecs = embedder.embed([c.text for c in index.chunks])
    assert len(vecs) == len(index.chunks)
    assert len({len(v) for v in vecs}) == 1  # uniform dimensionality
    out = hybrid_retrieve(
        "What INR range for warfarin in atrial fibrillation?", index, k=3
    )
    assert len(out) == 3
    assert any("Warfarin" in r.citation for r in out)
