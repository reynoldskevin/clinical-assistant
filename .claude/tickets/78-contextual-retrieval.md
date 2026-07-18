---
id: 78
title: Contextual retrieval — index each chunk with a situating context (BM25 + dense)
status: ready-for-merge
depends_on: []
branch: ticket/78-contextual-retrieval
base_branch: main
test_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest tests/test_retrieval.py -q'"
full_suite_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest -q'"
attempts: 0
---

## Description
Stretch goal #10: apply Anthropic's "Contextual Retrieval" technique to the guideline RAG pipeline (built in T48). Today both BM25 and the dense embeddings index ONLY each chunk's body text (`Chunk.text`); the `source_title` and `section` are ignored and there is no per-chunk situating context, so a query that matches a section's topic but not its body words can miss the right chunk. This ticket gives each chunk a short situating **context** — an authored sentence in the corpus, falling back to composing "{title}. {section}." when none is authored — and prepends that context to the text used for BOTH the BM25 index and the dense embedding. The retrieved/citable content (`RetrievedChunk.text`, `.citation`) stays body-only, so the context is purely an indexing aid and the existing citation/answer contracts are unchanged. Deterministic and fully offline (no runtime LLM); the authored context lives in the committed corpus.

## Acceptance criteria
- [ ] AC1 — `Chunk` gains a `context: str` field. Every chunk parsed from the corpus carries a non-empty context.
- [ ] AC2 (authored) — `_parse_markdown` reads an authored context from a `<!-- context: <sentence> -->` comment inside a section into `Chunk.context` (exact text, trimmed); the comment is NOT included in the chunk body `text`.
- [ ] AC3 (fallback) — when a section has no authored context comment, `Chunk.context` falls back to exactly `"{source_title}. {section}."`.
- [ ] AC4 (authored in corpus) — at least one committed-corpus chunk carries an authored context that differs from the pure title/section fallback (the corpus actually authors situating sentences).
- [ ] AC5 (contextual indexing) — BM25 and the dense embedding both index `context + body` (not body alone), so a term appearing ONLY in a chunk's context (not in any body) retrieves that chunk via `hybrid_retrieve`.
- [ ] AC6 (no leak / no regression) — `RetrievedChunk.text` and `.citation` remain body-only (context is not prepended to the returned text); the full existing retrieval suite still passes (9 chunks, exact citations, warfarin/INR ranking, determinism, tool contract, tracer).

## Test plan (orchestrator authors these; LOCKED)
- py (extend `sidecar/tests/test_retrieval.py`): every corpus chunk has non-empty `.context` (AC1); authored-comment parse (AC2); title/section fallback (AC3); ≥1 corpus chunk authored beyond fallback (AC4); context-only sentinel term retrieves its chunk via a synthetic tmp corpus + `.context` contains the sentinel (AC5); context does not leak into `.text`/`.citation` (AC6). The rest of the file (locked T48 contract) must stay green — regression guard for AC6.
