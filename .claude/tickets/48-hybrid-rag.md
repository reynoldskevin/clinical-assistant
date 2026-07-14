---
id: 48
title: Guideline corpus + hybrid retrieval (BM25 + dense) + Cohere rerank + evidence-retriever tool
status: ready-for-merge
depends_on: []
branch: ticket/48-hybrid-rag
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_retrieval.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Week 2 Stage 2, requirement 2 (basic hybrid RAG). Small, redistributable/synthetic clinical-guideline snippets under `sidecar/corpus/`, each chunk carrying a source citation (title + section), reproducible from the repo alone. Typed protocols `EmbeddingClient`, `VectorIndex`, `Reranker` (Cohere impl), each with an in-repo fixture stub so offline CI needs no network/keys. Hybrid retrieve = sparse (BM25) + dense → Cohere Rerank → top-k grounded chunks, wired as the `evidence-retriever` worker's tool; log retrieval hits + rerank scores. Dense uses a lightweight in-process index (hnswlib/numpy) behind `VectorIndex` — no dockerized Qdrant (deferred T58). Independent of T46/T47; may build on a parallel branch off main, converges at T49.

## Acceptance criteria
- [ ] `build_index` rebuilds deterministically from the committed corpus (chunk count + citations asserted).
- [ ] `EmbeddingClient` / `VectorIndex` / `Reranker` protocols + in-repo stubs; stubbed hybrid retrieve is deterministic in CI (no network/keys).
- [ ] Hybrid retrieve = BM25 + dense → Cohere rerank → top-k; a guideline question returns cited chunks; only top-k feeds the answer.
- [ ] `evidence-retriever` tool exposed; retrieval hits + rerank scores logged via `TraceCollector`.
- [ ] Live Cohere path smoke-tested (guarded, skipped without a key).

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_retrieval.py`: deterministic build_index (count+citations); stubbed BM25+dense fusion ordering; rerank reorders to expected top-k; each returned chunk carries a citation; empty/miss handled.
