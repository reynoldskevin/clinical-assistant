"""Guideline corpus + hybrid retrieval (BM25 + dense) -> rerank -> top-k.

A small, redistributable/synthetic clinical-guideline corpus lives under
``sidecar/corpus/``; each chunk carries a source citation (title + section) and
is reproducible from the repo alone. Retrieval fuses a pure-Python Okapi BM25
sparse ranker with a deterministic in-process dense index (stub, hashed
embeddings), reciprocal-rank-fuses the two candidate lists, reranks the
candidates, and returns the top-k grounded chunks.

Everything on the tested path is pure-Python + stdlib + pydantic: BM25, the
vector index, the stub embedder, and the stub reranker are implemented here so
offline CI needs no numpy/hnswlib/rank_bm25/cohere and no network or API keys.
The real Cohere reranker (``CohereReranker``) imports the ``cohere`` SDK LAZILY
inside ``.rerank`` — mirroring ``factory.build_message_creator`` — so
constructing it (and importing this module) never requires the SDK.
"""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from contracts import EvidenceQueryInput

# Absolute path to the committed guideline corpus (derived from this file).
CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")

# Dimensionality of the deterministic stub embeddings.
_EMBED_DIM = 256


# --- tokenizer ----------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase alnum tokenizer (mirrors the test's ``_tokens`` helper)."""
    return [
        t
        for t in "".join(c.lower() if c.isalnum() else " " for c in text).split()
        if t
    ]


# --- chunk / result value objects ---------------------------------------------

@dataclass(frozen=True)
class Chunk:
    """One cited section of a guideline document."""

    chunk_id: str
    source_title: str
    section: str
    text: str
    citation: str


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieved chunk paired with its rerank score."""

    chunk: Chunk
    score: float

    @property
    def citation(self) -> str:
        return self.chunk.citation

    @property
    def text(self) -> str:
        return self.chunk.text


# --- typed protocols ----------------------------------------------------------

@runtime_checkable
class EmbeddingClient(Protocol):
    """Turns texts into dense vectors of uniform dimensionality."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


@runtime_checkable
class VectorIndex(Protocol):
    """A dense nearest-neighbour index over added vectors."""

    def add(self, vectors: list[list[float]]) -> None:
        ...

    def search(self, vector: list[float], k: int) -> list[tuple[int, float]]:
        ...


@runtime_checkable
class Reranker(Protocol):
    """Reorders candidate documents by relevance to a query."""

    def rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        ...


# --- deterministic stub embeddings --------------------------------------------

class StubEmbeddingClient:
    """Deterministic, network-free embeddings: hashed bag-of-tokens.

    Each token is hashed into one of ``dim`` buckets and its count accumulated,
    then the vector is L2-normalised. Same input -> identical output; uniform
    dimensionality across all texts.
    """

    def __init__(self, dim: int = _EMBED_DIM) -> None:
        self._dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


# --- in-process cosine-similarity vector index --------------------------------

class InProcessVectorIndex:
    """Pure-Python cosine-similarity index; deterministic, tie-break index asc."""

    def __init__(self) -> None:
        self._vectors: list[list[float]] = []

    def add(self, vectors: list[list[float]]) -> None:
        self._vectors.extend([list(v) for v in vectors])

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    def search(self, vector: list[float], k: int) -> list[tuple[int, float]]:
        scored = [
            (i, self._cosine(vector, v)) for i, v in enumerate(self._vectors)
        ]
        # Best first; tie-break by index ascending (negate score, then index).
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[: max(0, k)]


# --- pure-Python Okapi BM25 ---------------------------------------------------

class BM25:
    """Pure-Python Okapi BM25 over a fixed tokenized corpus."""

    def __init__(
        self,
        corpus_tokens: list[list[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._corpus_tokens = [list(doc) for doc in corpus_tokens]
        self._k1 = k1
        self._b = b
        self._n = len(self._corpus_tokens)
        self._doc_lengths = [len(doc) for doc in self._corpus_tokens]
        self._avgdl = (
            sum(self._doc_lengths) / self._n if self._n else 0.0
        )
        # Per-document term frequencies + document frequencies per term.
        self._term_freqs: list[dict[str, int]] = []
        doc_freq: dict[str, int] = {}
        for doc in self._corpus_tokens:
            freqs: dict[str, int] = {}
            for token in doc:
                freqs[token] = freqs.get(token, 0) + 1
            self._term_freqs.append(freqs)
            for token in freqs:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        self._idf: dict[str, float] = {}
        for token, df in doc_freq.items():
            # Okapi BM25 idf with the standard +1 to keep it non-negative.
            self._idf[token] = math.log(1.0 + (self._n - df + 0.5) / (df + 0.5))

    def scores(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * self._n
        for token in query_tokens:
            idf = self._idf.get(token)
            if idf is None:
                continue
            for i in range(self._n):
                freq = self._term_freqs[i].get(token, 0)
                if freq == 0:
                    continue
                dl = self._doc_lengths[i]
                denom = freq + self._k1 * (
                    1.0 - self._b + self._b * (dl / self._avgdl if self._avgdl else 0.0)
                )
                scores[i] += idf * (freq * (self._k1 + 1.0)) / denom
        return scores


# --- corpus parsing + index ---------------------------------------------------

def _parse_markdown(path: str) -> list[Chunk]:
    """Parse one guideline .md into cited section chunks.

    ``# `` line = document title. Each ``## Section`` begins one chunk whose
    text is the section body up to the next ``## `` or EOF, EXCLUDING heading
    lines, HTML comments, and the file preamble before the first section.
    """
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    title = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            break

    chunks: list[Chunk] = []
    section: Optional[str] = None
    body: list[str] = []

    def flush() -> None:
        if section is None:
            return
        text = "\n".join(body).strip()
        if not text:
            return
        citation = f"{title} — {section}"
        chunk_id = _chunk_id(path, section)
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                source_title=title,
                section=section,
                text=text,
                citation=citation,
            )
        )

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            flush()
            section = stripped[3:].strip()
            body = []
            continue
        if section is None:
            # Preamble before the first section — skipped entirely.
            continue
        if stripped.startswith("#"):
            # Any heading line is excluded from chunk text.
            continue
        if stripped.startswith("<!--"):
            # HTML comment — excluded from chunk text.
            continue
        body.append(line)

    flush()
    return chunks


def _chunk_id(path: str, section: str) -> str:
    """Deterministic, unique chunk id from filename + section."""
    base = os.path.splitext(os.path.basename(path))[0]
    slug = "-".join(_tokenize(section))
    return f"{base}:{slug}"


@dataclass
class RetrievalIndex:
    """Holds the parsed chunks plus the sparse + dense retrieval structures."""

    chunks: list[Chunk]
    bm25: BM25
    embedding_client: EmbeddingClient
    vector_index: VectorIndex
    chunk_tokens: list[list[str]] = field(default_factory=list)


def build_index(
    corpus_dir: str = CORPUS_DIR,
    *,
    embedding_client: Optional[EmbeddingClient] = None,
) -> RetrievalIndex:
    """Build a deterministic retrieval index from the committed corpus."""
    embedder: EmbeddingClient = embedding_client or StubEmbeddingClient()

    filenames = sorted(
        f for f in os.listdir(corpus_dir) if f.endswith(".md")
    )
    chunks: list[Chunk] = []
    for name in filenames:
        chunks.extend(_parse_markdown(os.path.join(corpus_dir, name)))

    chunk_tokens = [_tokenize(c.text) for c in chunks]
    bm25 = BM25(chunk_tokens)

    vectors = embedder.embed([c.text for c in chunks])
    vector_index = InProcessVectorIndex()
    vector_index.add(vectors)

    return RetrievalIndex(
        chunks=chunks,
        bm25=bm25,
        embedding_client=embedder,
        vector_index=vector_index,
        chunk_tokens=chunk_tokens,
    )


# --- build-once guideline index singleton -------------------------------------

# Process-wide cache for the committed guideline corpus index. Built lazily on
# first use and reused across every request so the index is never rebuilt per
# ``/ask``.
_GUIDELINE_INDEX: Optional[RetrievalIndex] = None


def get_guideline_index() -> RetrievalIndex:
    """Return the shared guideline index, building it once on first call.

    Builds the committed 9-chunk corpus via ``build_index()`` on first call and
    memoizes it in the module-global ``_GUIDELINE_INDEX``; subsequent calls
    return the same object without rebuilding.
    """
    global _GUIDELINE_INDEX
    if _GUIDELINE_INDEX is None:
        _GUIDELINE_INDEX = build_index()
    return _GUIDELINE_INDEX


# --- rerankers ----------------------------------------------------------------

class StubReranker:
    """Deterministic offline reranker: lexical token-overlap scoring.

    Each document scores by the count of its tokens that appear in the query.
    Sort desc; tie-break by original index ascending; return top_k pairs. A
    document sharing query tokens outranks an unrelated one.
    """

    def rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        query_tokens = set(_tokenize(query))
        scored: list[tuple[int, float]] = []
        for i, doc in enumerate(documents):
            overlap = sum(1 for t in _tokenize(doc) if t in query_tokens)
            scored.append((i, float(overlap)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[: max(0, top_k)]


class CohereReranker:
    """Cohere-backed reranker. LAZY: imports ``cohere`` only in ``.rerank``.

    Constructing this class never imports the SDK or touches the network
    (mirroring ``factory.build_message_creator``); only ``.rerank`` imports
    cohere and calls the API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "rerank-english-v3.0",
    ) -> None:
        self._api_key = api_key
        self._model = model

    def rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        import cohere  # lazy: only needed when actually reranking via the API

        client = cohere.Client(self._api_key or os.environ.get("COHERE_API_KEY"))
        response = client.rerank(
            query=query,
            documents=documents,
            top_n=top_k,
            model=self._model,
        )
        return [
            (result.index, float(result.relevance_score))
            for result in response.results
        ]


def build_reranker() -> Reranker:
    """Return a Cohere reranker when configured, else a deterministic stub.

    Mirrors ``factory.build_tracer``: only when ``COHERE_API_KEY`` is set AND
    the ``cohere`` SDK imports successfully do we return a ``CohereReranker``;
    any missing key or import failure degrades to ``StubReranker``.
    """
    if not os.environ.get("COHERE_API_KEY"):
        return StubReranker()
    try:
        import cohere  # noqa: F401 - presence check only; imported lazily in rerank

        return CohereReranker()
    except Exception:  # noqa: BLE001 - never let a missing SDK break the offline path
        return StubReranker()


# --- hybrid retrieve ----------------------------------------------------------

def _reciprocal_rank_fusion(
    rankings: list[list[int]], *, rrf_k: int = 60
) -> list[int]:
    """Fuse ranked index lists via reciprocal-rank fusion.

    Returns fused chunk indices best-first; deterministic, tie-break by index
    ascending among equal RRF scores.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (rrf_k + rank + 1)
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    return [idx for idx, _ in ordered]


def hybrid_retrieve(
    query: str,
    index: RetrievalIndex,
    *,
    reranker: Optional[Reranker] = None,
    k: int = 3,
    candidate_k: int = 6,
) -> list[RetrievedChunk]:
    """BM25 + dense -> RRF -> rerank -> top-k grounded, cited chunks.

    An empty/whitespace query returns ``[]``. An out-of-corpus query never
    raises — it returns at most ``k`` cited chunks. Deterministic offline.
    """
    if not query or not query.strip():
        return []

    reranker = reranker or build_reranker()
    n = len(index.chunks)
    if n == 0:
        return []

    query_tokens = _tokenize(query)

    # Sparse ranking (BM25), best first.
    bm25_scores = index.bm25.scores(query_tokens)
    bm25_ranking = sorted(range(n), key=lambda i: (-bm25_scores[i], i))

    # Dense ranking (stub embeddings + cosine index), best first.
    query_vec = index.embedding_client.embed([query])[0]
    dense_hits = index.vector_index.search(query_vec, k=n)
    dense_ranking = [i for i, _ in dense_hits]

    # Fuse and take candidate_k candidates.
    fused = _reciprocal_rank_fusion([bm25_ranking, dense_ranking])
    candidate_indices = fused[: max(1, candidate_k)]

    candidate_docs = [index.chunks[i].text for i in candidate_indices]
    reranked = reranker.rerank(query, candidate_docs, top_k=k)

    out: list[RetrievedChunk] = []
    for local_idx, score in reranked[:k]:
        chunk = index.chunks[candidate_indices[local_idx]]
        out.append(RetrievedChunk(chunk=chunk, score=float(score)))
    return out


# --- evidence-retriever tool --------------------------------------------------

def build_evidence_retriever_tool(
    index: RetrievalIndex,
    *,
    reranker: Optional[Reranker] = None,
    tracer: Any = None,
    k: int = 3,
) -> dict[str, Any]:
    """Wire the guideline corpus into an ``evidence_retriever`` ToolSpec.

    Returns ``{name, description, input_schema, handler}`` exactly like
    ``factory.build_search_tool``. The handler validates its input via
    ``EvidenceQueryInput`` (strict + required ``query``); the effective top-k is
    the build-time ``k`` by default, overridden by an EXPLICIT ``top_k`` in the
    tool input (detected via ``model_fields_set``). Returns JSON-serializable
    rows ``{citation, text, score}`` and, when a ``tracer`` is given, records the
    hits via ``tracer.record_retrieval``.
    """

    def handler(pid: int, inp: Any) -> list[dict[str, Any]]:
        data = EvidenceQueryInput.model_validate(inp)
        top_k = data.top_k if "top_k" in data.model_fields_set else k
        hits = hybrid_retrieve(data.query, index, reranker=reranker, k=top_k)
        rows = [
            {"citation": h.citation, "text": h.text, "score": h.score}
            for h in hits
        ]
        if tracer is not None:
            tracer.record_retrieval(
                [{"citation": r["citation"], "score": r["score"]} for r in rows]
            )
        return rows

    return {
        "name": "evidence_retriever",
        "description": (
            "Retrieve grounded clinical-guideline evidence for a question. "
            "Runs hybrid retrieval (BM25 + dense) over a synthetic guideline "
            "corpus and reranks to the top matches. Returns cited snippet rows "
            "— each with a citation (title + section), the guideline text, and a "
            "relevance score. Supply a 'query'; 'top_k' is optional. The corpus "
            "is patient-independent."
        ),
        "input_schema": EvidenceQueryInput.model_json_schema(),
        "handler": handler,
    }
