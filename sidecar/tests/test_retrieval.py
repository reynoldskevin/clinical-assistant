"""Acceptance tests for ticket 48 — guideline corpus + hybrid retrieval.

Locked contract (orchestrator-authored, TDD): the implementer writes production
code in sidecar/retrieval.py (+ small additions to contracts.py and
observability.py) to satisfy these. Tests must NOT be edited by the implementer.

Everything here runs offline and deterministically: no network, no API keys. The
real Cohere path is exercised only by a guarded smoke test that skips without a
COHERE_API_KEY. BM25 + dense fusion + the stub reranker are pure-Python so CI needs
nothing beyond the stdlib + pydantic.
"""

import json
import os

import pytest

from retrieval import (
    CORPUS_DIR,
    BM25,
    Chunk,
    CohereReranker,
    InProcessVectorIndex,
    RetrievedChunk,
    StubEmbeddingClient,
    StubReranker,
    build_evidence_retriever_tool,
    build_index,
    build_reranker,
    hybrid_retrieve,
)
from observability import TraceCollector
from contracts import EvidenceQueryInput


# The committed corpus is the contract: 3 synthetic guideline files, 3 sections
# each = 9 chunks. If the corpus changes, this expected set changes with it.
EXPECTED_CITATIONS = {
    "Anticoagulation Management (Synthetic Guideline) — Warfarin INR Monitoring",
    "Anticoagulation Management (Synthetic Guideline) — Drug Interactions",
    "Anticoagulation Management (Synthetic Guideline) — Bleeding Risk Assessment",
    "Type 2 Diabetes Management (Synthetic Guideline) — Glycemic Targets",
    "Type 2 Diabetes Management (Synthetic Guideline) — HbA1c Monitoring",
    "Type 2 Diabetes Management (Synthetic Guideline) — Metformin First-Line Therapy",
    "Hypertension Management (Synthetic Guideline) — Blood Pressure Targets",
    "Hypertension Management (Synthetic Guideline) — Lifestyle Modification",
    "Hypertension Management (Synthetic Guideline) — Pharmacologic Treatment",
}


# --- build_index: deterministic, cited chunks ---------------------------------

def test_build_index_is_deterministic_from_the_committed_corpus():
    index_a = build_index()
    index_b = build_index()

    # Exact chunk count is asserted from the committed corpus.
    assert len(index_a.chunks) == 9
    assert len(index_b.chunks) == 9

    # Rebuild is byte-for-byte deterministic: same ids, citations, order.
    ids_a = [c.chunk_id for c in index_a.chunks]
    ids_b = [c.chunk_id for c in index_b.chunks]
    assert ids_a == ids_b
    assert [c.citation for c in index_a.chunks] == [c.citation for c in index_b.chunks]
    # chunk ids are unique
    assert len(set(ids_a)) == 9


def test_default_corpus_dir_exists_and_is_used():
    assert os.path.isdir(CORPUS_DIR)
    # building from the explicit default dir yields the same chunk count.
    assert len(build_index(CORPUS_DIR).chunks) == 9


def test_every_chunk_carries_a_source_citation_title_and_section():
    index = build_index()
    citations = {c.citation for c in index.chunks}
    assert citations == EXPECTED_CITATIONS
    for c in index.chunks:
        assert isinstance(c, Chunk)
        assert c.source_title and c.section
        # citation is "Title — Section" and is non-empty
        assert c.citation == f"{c.source_title} — {c.section}"
        assert c.text.strip() != ""


def test_preamble_and_comments_are_not_chunks():
    # The SYNTHETIC/NO-PHI HTML comment lives in the file preamble (before the
    # first section) and must never surface as chunk text.
    index = build_index()
    for c in index.chunks:
        assert "SYNTHETIC" not in c.text  # comment text excluded
        assert not c.text.lstrip().startswith("#")  # heading lines excluded


# --- BM25 (sparse) ------------------------------------------------------------

def test_bm25_ranks_the_lexically_matching_chunk_first():
    index = build_index()
    bm25 = index.bm25
    scores = bm25.scores(_tokens("warfarin INR target range monitoring stable"))
    assert len(scores) == 9
    top = max(range(9), key=lambda i: scores[i])
    assert index.chunks[top].section == "Warfarin INR Monitoring"


def test_bm25_scores_are_deterministic():
    index = build_index()
    q = _tokens("metformin first line therapy diabetes")
    assert index.bm25.scores(q) == index.bm25.scores(q)


# --- dense retrieval (stub embeddings + in-process index) ---------------------

def test_stub_dense_retrieval_is_deterministic():
    embed = StubEmbeddingClient()
    texts = ["alpha beta", "gamma delta", "alpha gamma"]
    vecs = embed.embed(texts)
    # deterministic + stable dimensionality
    assert vecs == embed.embed(texts)
    assert len({len(v) for v in vecs}) == 1

    idx = InProcessVectorIndex()
    idx.add(vecs)
    qvec = embed.embed(["alpha beta"])[0]
    hits = idx.search(qvec, k=2)
    assert len(hits) == 2
    # returns (chunk_index, score) pairs, best first, deterministic
    assert hits == idx.search(qvec, k=2)
    assert hits[0][0] == 0  # the identical document ranks first
    assert hits[0][1] >= hits[1][1]


# --- hybrid retrieve = BM25 + dense -> rerank -> top-k ------------------------

def test_hybrid_retrieve_returns_cited_chunks_top_k_only():
    index = build_index()
    out = hybrid_retrieve("How often should warfarin INR be monitored?", index, k=3)

    assert isinstance(out, list)
    assert len(out) == 3  # only top-k feeds the answer
    for r in out:
        assert isinstance(r, RetrievedChunk)
        assert r.citation in EXPECTED_CITATIONS  # every returned chunk is cited
        assert r.text.strip() != ""
    # a warfarin/INR question surfaces the warfarin monitoring guidance
    assert any("Warfarin INR Monitoring" in r.citation for r in out)


def test_hybrid_retrieve_is_deterministic_offline():
    index = build_index()
    a = hybrid_retrieve("blood pressure target hypertension", index, k=3)
    b = hybrid_retrieve("blood pressure target hypertension", index, k=3)
    assert [r.citation for r in a] == [r.citation for r in b]


def test_rerank_reorders_candidates_and_slices_to_top_k():
    index = build_index()

    class ReverseReranker:
        """Deterministic reranker: reverses the candidate order, then top_k."""

        def rerank(self, query, documents, top_k):
            order = list(range(len(documents)))[::-1]
            return [(i, float(len(documents) - rank)) for rank, i in enumerate(order)][:top_k]

    out = hybrid_retrieve("diabetes hba1c", index, reranker=ReverseReranker(), k=2)
    assert len(out) == 2
    # scores are non-increasing (reranker output order is preserved)
    assert out[0].score >= out[1].score


def test_empty_query_returns_no_hits_and_gibberish_does_not_crash():
    index = build_index()
    assert hybrid_retrieve("   ", index, k=3) == []
    # an out-of-corpus query must not raise; it returns at most k cited chunks.
    out = hybrid_retrieve("zzqqx nonexistent terms", index, k=3)
    assert isinstance(out, list)
    assert len(out) <= 3
    for r in out:
        assert r.citation in EXPECTED_CITATIONS


# --- evidence-retriever tool --------------------------------------------------

def test_evidence_retriever_tool_is_wellformed_and_query_required():
    index = build_index()
    spec = build_evidence_retriever_tool(index)

    assert spec["name"] == "evidence_retriever"
    assert spec["description"]
    schema = spec["input_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["required"] == ["query"]
    assert "top_k" in schema["properties"]  # optional
    assert callable(spec["handler"])


def test_evidence_retriever_handler_returns_json_serializable_cited_rows():
    index = build_index()
    spec = build_evidence_retriever_tool(index, k=3)

    rows = spec["handler"](42, {"query": "warfarin INR monitoring frequency"})
    assert isinstance(rows, list) and rows
    for row in rows:
        assert row["citation"] in EXPECTED_CITATIONS
        assert row["text"].strip() != ""
        assert isinstance(row["score"], (int, float))
    # the whole result must be JSON-serializable (it is fed back to the model)
    json.dumps(rows)


def test_evidence_retriever_respects_top_k_from_tool_input():
    index = build_index()
    spec = build_evidence_retriever_tool(index, k=5)
    rows = spec["handler"](1, {"query": "hypertension blood pressure", "top_k": 2})
    assert len(rows) == 2


def test_evidence_retriever_logs_hits_and_rerank_scores_via_tracer():
    index = build_index()

    class RecordingTracer:
        def __init__(self):
            self.hits = None

        def record_retrieval(self, hits):
            self.hits = hits

    tracer = RecordingTracer()
    spec = build_evidence_retriever_tool(index, tracer=tracer, k=3)
    spec["handler"](7, {"query": "diabetes hba1c target"})

    assert tracer.hits is not None
    assert len(tracer.hits) == 3
    for h in tracer.hits:
        assert h["citation"] in EXPECTED_CITATIONS
        assert isinstance(h["score"], (int, float))


# --- TraceCollector.record_retrieval (additive) -------------------------------

def test_trace_collector_records_retrieval_hits_in_summary():
    trace = TraceCollector(model="claude-opus-4-8")
    hits = [
        {"citation": "Guide — A", "score": 0.9},
        {"citation": "Guide — B", "score": 0.4},
    ]
    trace.record_retrieval(hits)
    s = trace.summary()
    assert s["retrieval_hits"] == hits
    # additive: existing counters still present + unaffected
    assert s["tool_calls"] == 0


def test_evidence_retriever_logs_into_a_real_trace_collector():
    index = build_index()
    trace = TraceCollector(model="claude-opus-4-8")
    spec = build_evidence_retriever_tool(index, tracer=trace, k=2)
    spec["handler"](1, {"query": "warfarin bleeding risk"})
    hits = trace.summary()["retrieval_hits"]
    assert len(hits) == 2
    assert all(h["citation"] in EXPECTED_CITATIONS for h in hits)


# --- EvidenceQueryInput contract ---------------------------------------------

def test_evidence_query_input_contract():
    schema = EvidenceQueryInput.model_json_schema()
    assert schema["required"] == ["query"]
    parsed = EvidenceQueryInput.model_validate({"query": "x"})
    assert parsed.query == "x"
    assert parsed.top_k == 3  # default
    # unknown fields rejected (strict, mirroring the other tool inputs)
    with pytest.raises(Exception):
        EvidenceQueryInput.model_validate({"query": "x", "bogus": 1})


# --- Cohere reranker: guarded, offline-safe -----------------------------------

def test_build_reranker_falls_back_to_stub_without_a_key(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    reranker = build_reranker()
    # Without a key we get a deterministic offline stub, not a Cohere client.
    assert isinstance(reranker, StubReranker)
    out = reranker.rerank("query terms", ["query terms doc", "unrelated"], top_k=1)
    assert out and out[0][0] == 0  # the lexically-overlapping doc wins


def test_cohere_reranker_does_not_require_the_sdk_at_import_time():
    # Constructing the class must not import cohere (lazy). Instantiation is cheap;
    # only .rerank() would touch the network — which the guarded smoke test covers.
    r = CohereReranker(api_key="unused-in-this-test")
    assert hasattr(r, "rerank")


@pytest.mark.skipif(
    not os.environ.get("COHERE_API_KEY"),
    reason="live Cohere smoke test — needs COHERE_API_KEY",
)
def test_cohere_rerank_live_smoke():
    index = build_index()
    reranker = build_reranker()
    assert isinstance(reranker, CohereReranker)
    out = hybrid_retrieve(
        "What INR range for warfarin in atrial fibrillation?",
        index,
        reranker=reranker,
        k=3,
    )
    assert len(out) == 3
    assert any("Warfarin" in r.citation for r in out)


# --- helpers ------------------------------------------------------------------

def _tokens(text):
    """Mirror the module's tokenizer closely enough for BM25 assertions."""
    return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t]
