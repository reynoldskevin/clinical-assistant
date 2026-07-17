---
id: 058b
title: Qdrant-backed VectorIndex + build_vector_index factory (lazy, degrading)
status: todo
depends_on: [058a]
branch: ticket/58b-qdrant-vector-index
base_branch: ticket/58a-resilience-primitives
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_qdrant_index.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Migrate the dense vector store from the pure-Python `InProcessVectorIndex` to a real Qdrant service — behind the existing `VectorIndex` Protocol, following the same lazy-import-and-degrade contract as `CohereEmbeddingClient`/`CohereReranker`. Add a `QdrantVectorIndex` that upserts vectors into a collection and searches it, importing `qdrant_client` LAZILY (never at construction) and wrapping every remote call in T58a's `call_resilient` (timeout + retry + a shared `CircuitBreaker`) so a Qdrant outage fails fast without taking the sidecar down. Add a `build_vector_index()` factory that returns a `QdrantVectorIndex` only when `QDRANT_URL` is set AND `qdrant_client` imports, else the deterministic `InProcessVectorIndex`; wire it into `build_index()` so offline CI stays network-free and reproducible while production uses Qdrant. Stacked on T58a (imports `resilience`).

## Acceptance criteria
- [ ] `QdrantVectorIndex(url, collection, dim, *, breaker=None, client_factory=None, timeout=..., retries=...)` satisfies the `VectorIndex` Protocol: `add(vectors)` upserts the vectors (deterministic integer ids by insertion order) and `search(vector, k)` returns `list[tuple[int, float]]` best-first — the SAME shape `InProcessVectorIndex.search` returns, so `hybrid_retrieve` is agnostic to which index is used.
- [ ] Constructing `QdrantVectorIndex` does NOT import `qdrant_client` or open a connection; the SDK is imported lazily inside the method that first needs the client (mirrors `CohereReranker`). `client_factory` is injectable so tests supply a fake client with no SDK or network.
- [ ] Every remote Qdrant call goes through T58a `call_resilient` with a per-call `timeout`, bounded `retries`, and a `CircuitBreaker`; when the breaker is open, calls short-circuit (`CircuitOpenError`) instead of hitting the dead service.
- [ ] `build_vector_index()` returns a `QdrantVectorIndex` ONLY when `QDRANT_URL` is set and `qdrant_client` imports successfully; a missing env var OR an import failure degrades to `InProcessVectorIndex` (never raises). Mirrors `build_embedding_client`/`build_reranker`.
- [ ] `build_index()` obtains its vector index via `build_vector_index()` (not a hard-coded `InProcessVectorIndex()`), so with no `QDRANT_URL` the offline path is behaviourally identical to today and the existing `test_retrieval.py` stays green.
- [ ] No new hard dependency for CI: `qdrant-client` is added to `requirements.txt` as an optional/lazy backend (documented like `cohere`), and the test suite runs without it installed.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_qdrant_index.py` — a fake Qdrant client (injected via `client_factory`) exercises `add`/`search` returning the Protocol shape; `build_vector_index()` returns `InProcessVectorIndex` when `QDRANT_URL` is unset and when the lazy import fails (monkeypatched), and `QdrantVectorIndex` when configured; a fake client raising drives the resilience path (retry then open breaker → short-circuit); `build_index()` uses the factory (no `QDRANT_URL` ⇒ in-process, index still builds the committed corpus).
