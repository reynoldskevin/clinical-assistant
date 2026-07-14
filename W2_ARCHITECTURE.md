# W2_ARCHITECTURE — Clinical Co-Pilot, Week 2

> Document ingestion + VLM extraction, hybrid RAG + rerank, a LangGraph
> supervisor/worker graph, a machine-readable citation contract with a visual PDF
> bounding-box overlay, and an expanded eval/observability surface — built
> **additively** on the Week 1 architecture (`ARCHITECTURE.md`). Execution is
> decomposed in `W2_BUILD_PLAN.md`. This document is the canonical design +
> engineering reference and the home for the required testing-strategy,
> failure-mode, data-model, privacy, and backup sections.

## Scope & invariants

**The Week 2 job.** A physician prepping a follow-up visit needs to know *what
changed, what to pay attention to, and what evidence supports the
recommendation* — but the important recent information is in a scanned lab PDF
and a front-desk intake form, not in structured OpenEMR fields. The Co-Pilot must
ingest those documents, extract structured facts with citations, retrieve
guideline evidence, and return a grounded answer that separates patient-record
facts from guideline evidence — and stay useful when the scan is imperfect, the
record is incomplete, or the user asks a follow-up.

**Invariants carried from Week 1 (never violated by Week 2 work).**
1. Synthetic/demo data only. Never point any of this at real PHI without
   BAA/ZDR-covered infrastructure (that is the deferred M4 track).
2. No raw PHI in logs, traces, eval datasets, cost reports, or screenshots.
3. The read boundary stays pid-scoped, fail-closed, and audited.
4. **The schema is the source of truth.** Raw VLM output is validated before any
   downstream use; it never bypasses the contract.
5. One authoritative source per data type; no silent overwrites.
6. The Week 1 correlation ID propagates into every Week 2 hop (ingestion, worker
   handoffs, VLM calls, retrieval calls, FHIR writes).

---

## 1. System overview

```
browser card ──POST /ask (Bearer pid-JWT, X-Correlation-ID)──▶ sidecar server.py
                                                                    │
                     ┌──────────────────────  LangGraph supervisor  ┘
                     │   routes + records decisions (inspectable);
                     │   supervisor span → worker child spans
        ┌────────────┴──────────────┐
        ▼                           ▼
  intake-extractor worker     evidence-retriever worker
   • attach_and_extract        • hybrid retrieve (BM25 + Qdrant dense)
   • VLM extract (Claude        • Cohere Rerank → top-k guideline chunks
     vision) → strict schema
        │                           │
        ▼                           ▼
  OpenEMR read/write boundary   in-repo guideline corpus (authoritative)
  (read.php + upload, audited)     └─ built into Qdrant (derived, rebuildable)
        │
        ▼
  OpenEMR = source of truth
   • documents table  ← stored source PDF/form (content-hash keyed, idempotent)
   • derived FHIR/OpenEMR records ← extracted facts, document_id provenance
                                │
                                ▼
                     verification gate (extended) ──▶ answer + citations
                       • citation required per clinical claim
                       • patient-record facts vs guideline evidence separated
                       • bbox overlay data for PDF-sourced facts
```

**Component ownership.**

| Component | Owner / source of truth | Week 1 or new |
|---|---|---|
| Source documents (PDF, intake form) | OpenEMR `documents` table | new store, existing table |
| Derived lab/intake facts | OpenEMR record + `document_id` provenance | new |
| Guideline corpus | `sidecar/corpus/` (in-repo) | new |
| Vector index | Qdrant (derived from corpus; rebuildable) | new |
| Read/write boundary | `oe-module-ai-agent` (`read.php`, upload) | extended |
| Orchestration | LangGraph supervisor + workers | new (replaces single loop for W2 paths) |
| Verification gate | `sidecar/verification.py` | extended |
| Observability | Braintrust + structured logs | extended |
| Contracts | `sidecar/contracts.py` (Pydantic) | extended |

---

## 2. Document ingestion & extraction

**`attach_and_extract(patient_id, document_id, doc_type)`** — `doc_type ∈
{lab_pdf, intake_form}`. The source file is uploaded through the UI first (the
front desk / physician selects it on the AI Co-Pilot card → guarded module upload
endpoint), so by the time the agent runs the blob already lives in OpenEMR and the
tool references it by `document_id`. Steps:
1. **Store** (UI upload path, ahead of the tool) — the guarded upload endpoint
   writes the source blob to OpenEMR's `documents` table, keyed by `sha256(content)`
   per pid → **idempotent** (re-upload of the same bytes returns the existing
   `document_id`, no duplicate; content-hash dedup is staged at plan T62).
2. **Extract** with Claude vision over the rasterized page(s) → strict
   `LabFact` / `IntakeFact` objects. The VLM is instructed to return, per field:
   the value, a **verbatim quote**, the page, and a self-reported confidence.
3. **Validate** every returned object against the Pydantic schema *before* it is
   used. Fields the model cannot ground in a quote are marked `unsupported` and
   surfaced — never silently dropped, and never invented into the record.
4. **Persist** accepted facts as appropriate FHIR/OpenEMR records (e.g.
   `procedure_result` / derived observation) carrying `document_id` + extraction
   -run provenance. Re-ingest supersedes prior derived facts by run id.

**Vision-without-invention strategy.** Three layers make unsupported facts
visible: (a) the schema rejects malformed/missing required fields; (b) each field
must carry a verbatim quote that the OCR layer can re-locate on the page — a quote
that can't be located downgrades the field's confidence and flags it; (c) the
verification gate blocks/demotes any clinical claim in the final answer whose
citation doesn't resolve. A VLM can overstate confidence, so **confidence is
advisory, quote-locatability is authoritative**.

**Required extracted fields.**
- `LabFact`: test name, value, unit, reference range, collection date, abnormal
  flag, source citation (`{document_id, page, bbox, quote}`).
- `IntakeFact`: demographics (name/DOB/sex/contact as applicable), chief concern,
  current medications, allergies, family history, source citation.

---

## 3. Hybrid RAG + rerank (evidence grounding)

- **Corpus.** A small, redistributable/synthetic set of clinical-guideline
  snippets under `sidecar/corpus/`, each chunk carrying a source citation (title +
  section). The corpus is **the source of truth and lives in the repo** — the
  vector index is a derived, rebuildable artifact. This is what makes evidence
  reproducible from the repo alone.
- **Retrieval.** Sparse **BM25** + dense vectors (Cohere embeddings), fused, then
  **Cohere Rerank** reorders candidates; only the top-k grounded chunks reach the
  answer model. Nothing else is fed to the answer step.
- **MVP staging.** The MVP ships an **in-process dense index** (hnswlib/numpy)
  behind the `VectorIndex` protocol; the dockerized **Qdrant** service is staged at
  plan T58 as a drop-in implementation of the same protocol — no graph or gate
  change is needed to swap. The diagram and §5/§14 name Qdrant as the target
  implementation.
- **Separation of authority.** Guideline chunks are *evidence*, never
  *patient-record fact*. The answer renders them in a distinct section and cites
  them with `source_type: guideline`; a guideline can support a recommendation but
  can never stand in for a patient-specific value.
- **Swappable vendors.** `EmbeddingClient`, `VectorIndex`, `Reranker` are typed
  protocols; Qdrant/Cohere are one implementation each, with in-repo fixture stubs
  used by offline CI. Pinecone or a local cross-encoder can drop in without
  touching the graph or gate.

---

## 4. Multi-agent orchestration (LangGraph)

A **supervisor** node routes each request to one or both **workers** —
`intake-extractor` (document + extraction tools) and `evidence-retriever` (RAG
tools) — then synthesizes. Routing decisions are recorded and inspectable (logged
event + trace span), satisfying "make the supervisor's routing decisions
inspectable."

**What is preserved from Week 1 inside the graph.**
- Correlation ID flows into every node, VLM call, retrieval call, and FHIR write.
- Tracing: the supervisor is a parent span; each worker invocation is a **child
  span**; extraction and retrieval sub-calls are traceable within their worker
  spans.
- The **verification gate runs on the synthesized answer** before it leaves the
  graph — unchanged responsibility, extended checks (§6).
- The **pid-scoped boundary is unchanged**: workers read/write only through the
  audited module endpoints with the request's pid-JWT.

**Multi-turn.** Follow-up questions re-enter the graph with prior history via the
Week 1 `ConversationStore` semantics (in-memory, TTL, pid-scoped, ZDR). A
follow-up reuses already-extracted facts rather than re-running extraction.

**Critic worker** is explicitly **extension**, not core, per the brief.

---

## 5. Data model, authority, lineage, access, validation

| Data type | Authoritative source | Lineage | Access control | Validation rules |
|---|---|---|---|---|
| Source document | OpenEMR `documents` | uploaded via `attach_and_extract`; `sha256` keyed | pid-scoped boundary, audited; agent principal only | mime allowlist, size cap, one row per (pid, hash) |
| Extracted lab/intake fact | OpenEMR derived record | `derived_from = document:<id>` + `extraction_run:<id>` | boundary read only | strict `LabFact`/`IntakeFact` before persist; quote-locatable |
| Guideline chunk | `sidecar/corpus/` (repo) | committed text + `{title, section}` citation | public (no PHI); read-only at runtime | chunk schema; deterministic chunk ids |
| Vector embedding | Qdrant (derived) | built from corpus chunk id | internal service | rebuildable from corpus; not a source of truth |
| Citation record | agent output (derived) | references a record `ref` or a chunk id | returned to card | `Citation` schema; gate-verified |

**Data-authority rules.** OpenEMR is authoritative for anything patient-specific
(documents + derived facts). The repo corpus is authoritative for guideline text.
Qdrant and any cache are **derived and disposable**. No component silently
overwrites another's authoritative record; derived facts supersede by
extraction-run id, preserving history.

**Migration safety.** All Week 2 contract changes are **additive** to the six
Week 1 tool contracts (no breaking change). Every change is recorded in
`W2_MIGRATIONS.md`. Any new OpenEMR schema (e.g. an `ai_extraction_run`
provenance table, if introduced) uses Doctrine Migrations per `CLAUDE.md` — no
ad-hoc SQL.

---

## 6. Citation contract & verification

**Citation shape (machine-readable, required on every clinical claim):**
```json
{
  "source_type": "patient_record | guideline",
  "source_id": "document:42 | prescription:7 | guideline:ada-2024",
  "page_or_section": "p.2 | §Screening",
  "field_or_chunk_id": "hba1c | chunk:17",
  "quote_or_value": "HbA1c 8.1 % (ref 4.0–5.6)"
}
```
Patient-record facts (`source_type: patient_record`) and guideline evidence
(`source_type: guideline`) are rendered in **separate sections** of the answer.

**Verification gate extensions (on top of Week 1 V1–V3/V6/V7).**
- Citation-validity extends to document refs (`document:<id>`) and chunk refs
  (`guideline:*`/`chunk:*`), not just the Week 1 record refs.
- **Every clinical claim must carry a resolvable citation** — an uncited clinical
  claim is demoted ("not supported by the record") or blocked, reusing the Week 1
  verdict machinery (`pass` / `pass_with_flags` / `blocked` + safe fallback).
- Record-vs-evidence separation is enforced: a recommendation may cite a guideline,
  but a patient-specific value (a lab number, a med) must cite a patient-record
  source.

**PDF bounding-box overlay.** The VLM supplies the verbatim quote; a deterministic
OCR word-box locator (`pdfplumber` word geometry, Tesseract fallback for scanned
images) maps the quote to `[x, y, w, h]` in page coordinates. The citation carries
`page` + `bbox`; the card overlays the box on the rasterized page image. Because
coordinates come from OCR geometry rather than the model, the overlay is
verifiable and cannot be hallucinated; if the quote can't be located, the overlay
degrades gracefully (no box) rather than guessing.

---

## 7. Observability, SLOs, tracing, dashboards

**Structured logging (extends the Week 1 schema; no parallel convention).** New
PHI-free event types, searchable by `case_id`, `event_id`, `correlation_id`:
`ingestion.start`, `ingestion.complete`, `extraction.field` (per-field outcome:
ok / unsupported / low-confidence — **never the extracted value**),
`retrieval.hit` / `retrieval.miss`, `worker.handoff`, `eval.run`.

**Distributed tracing.** Supervisor span → worker child spans → extraction /
retrieval sub-spans. A full Week 2 request trace is reconstructable from the
correlation ID alone.

**Per-encounter metrics.** Tool sequence, latency by step, token usage, cost
estimate, retrieval hits, extraction confidence (aggregate, not values), and eval
outcome — all PHI-free.

**SLOs.** Document-ingestion p95 < target seconds; evidence-retrieval p95 <
target. (Concrete targets set from the T44/T45 baseline run and recorded against
`METRICS_WEEK1.md`.)

**Resilience.** Every outbound LLM + retrieval call has a timeout, bounded retry,
and a circuit breaker; a slow/absent dependency trips the breaker instead of
hanging the request.

**Health/readiness.** `/health` stays an unconditional liveness check. `/ready`
extends the Week 1 probes to also check **document storage, Qdrant, and Cohere**,
returning a **degraded** status (not binary up/down) that names the unavailable
dependency.

**Dashboards & alerts.** Panels: document-ingestion count, extraction field-level
pass rate, retrieval hit rate, supervisor routing decisions, and eval pass/fail
per category. Alerts: extraction-failure rate, RAG-retrieval latency, and
**eval-regression detection (>5% drop in any category)** — each with a documented
expected response action (extends `ALERTS.md`).

---

## 8. Eval-driven CI gate

**Golden set:** 50 in-repo cases (extends the Week 1 YAML harness + graders) with
boolean rubric categories: `schema_valid`, `citation_present`,
`factually_consistent`, `safe_refusal`, `no_phi_in_logs`. The golden set is
reproducible from the repo alone (see §10).

**PR-blocking gate:** the build fails if any category **regresses by more than 5%**
or drops below its pass threshold. The blocking (offline, no-secrets) suite also
runs: schema-validation tests, supervisor↔worker contract tests, extraction
regression tests, and full ingestion→answer integration tests using **fixture
documents + stubbed LLM/VLM**. **Dependency audit + security scan run on every
PR.** The live scored sweep (real LLM/Cohere/Qdrant) remains a non-blocking
scheduled/manual job as in Week 1.

---

## 9. Testing strategy

*Every test guards a documented failure mode.*

**Unit-tested (fast, no DB, no network).**
- Schema validators (`LabFact`, `IntakeFact`, `Citation`, `DocumentMetadata`,
  `GuidelineChunk`, `WorkerResult`) — *guards:* a malformed or hallucinated VLM
  field reaching a persisted record; a citation missing a required key.
- OCR bbox locator against known page geometry — *guards:* an overlay box drawn on
  the wrong value, or a crash when the quote is absent.
- Verification-gate extensions (uncited-claim demotion/block, record-vs-evidence
  split) — *guards:* an ungrounded clinical claim shipping to the physician.
- Retrieval fusion + rerank ordering with stubs — *guards:* silent loss of the
  correct chunk during BM25/dense fusion or rerank.

**Integration-tested (DB and/or in-process services, stubbed external LLM/VLM).**
- Ingestion flow: upload → `documents` row → extract → persist → boundary read —
  *guards:* duplicate/untraceable records; broken document→fact provenance.
- Idempotent re-ingest — *guards:* a re-upload creating a second record or a second
  derived-fact set.
- RAG pipeline end-to-end against a test Qdrant + stubbed Cohere — *guards:* a
  wiring regression that returns no results or un-reranked results.
- Supervisor↔worker contract test (`WorkerResult`) — *guards:* a worker changing
  its return shape and breaking the graph silently.
- Full ingestion→answer with fixture PDFs + stubbed models — *guards:* a
  cross-component regression invisible to unit tests.

**Evaluated via the golden set (agent behavior, live models).**
- Schema validity, citation presence, factual consistency, safe refusal, and
  no-PHI-in-logs across 50 cases — *guards:* behavioral regressions that
  deterministic tests can't catch (hallucination, over-confident extraction,
  unsafe answers, PHI leakage).

**Not tested (and why).**
- Third-party accuracy of Cohere Rerank / Claude vision internals — out of our
  control; we test *our* wiring and *our* validation of their outputs, not their
  model quality.
- Real-PHI paths — deferred to M4; Week 2 runs on synthetic data only.
- Qdrant/Cohere availability under production load — covered by SLO/alerting and
  the circuit breaker, not by unit tests.

---

## 10. Failure modes, debugging & incident response

| Failure | How to identify in logs | Recovery action |
|---|---|---|
| Document ingestion failure (upload/store) | `ingestion.start` with no `ingestion.complete` for the correlation ID; boundary audit shows no `documents` write | Retry upload (idempotent by hash); if storage down, `/ready` shows document-storage degraded → check the OpenEMR documents mount |
| Extraction schema violation | `extraction.field` events with `outcome=unsupported`/validation error; no derived-fact write | Fact is flagged, not persisted; surface "couldn't extract X"; re-run extraction or fall back to structured-only answer |
| RAG returns no results | `retrieval.miss` with zero hits; empty rerank input | Answer proceeds with patient-record facts only and states no guideline evidence was found — never fabricates evidence |
| Supervisor routing error | Supervisor span with no child worker spans, or a worker child span that errored | Circuit breaker / retry on the worker; if persistent, degrade to the Week 1 single-tool answer path |
| Vector index / reranker unavailable | `/ready` degraded (Qdrant/Cohere probe false); breaker open in trace | Serve record-only grounded answer; rebuild Qdrant from corpus if the index is corrupt (§ backup) |
| Overlay quote not locatable | bbox locator returns none; `extraction.field` low-confidence | Render citation without a box; flag the field for review |

Debugging entry point is always the **correlation ID**: it reconstructs the full
supervisor→worker→sub-call trace and joins it to the structured log events.

---

## 11. Privacy / PHI in analytics workflows

Traces, logs, eval datasets, cost reports, and screenshots must contain **no
patient identifiers, no raw document text, and no extracted clinical values**.

**Scrubbing approach.** (a) Log events carry ids and *outcomes*, never values —
e.g. `extraction.field {field: "hba1c", outcome: "ok"}`, never the number.
(b) Extraction/verification code logs refs, not content (the Week 1 PSR-3
context-array discipline). (c) The eval golden set and fixtures use only synthetic
patients from the loaded cohort and public/synthetic guideline text. (d) Bounding
-box overlay images are generated from synthetic documents only.

**Verified in CI.** A PHI-detection check (the `no_phi_in_logs` rubric category
plus a log-scanning test over emitted events) fails the build if identifier or
value patterns (SSN/MRN/name/DOB, lab-value shapes) appear in Week 2 log/trace
output. This extends the Week 1 V6 identifier-leak posture to the new event stream.

---

## 12. Backup & recovery

| Artifact | Backup (automatic) | Manual recovery | RPO / RTO |
|---|---|---|---|
| Source documents | OpenEMR DB + documents store backup (existing platform backup) | restore from platform backup | RPO = platform backup interval; RTO = restore time |
| Derived FHIR/OpenEMR facts | same DB backup; also **re-derivable** by re-running `attach_and_extract` on the stored source | re-ingest source documents (idempotent) | RPO ≈ 0 (re-derivable); RTO = re-ingest time |
| Guideline corpus | **in git** (`sidecar/corpus/`) | `git checkout` | RPO = last commit; RTO ≈ seconds |
| Vector index (Qdrant) | none needed — derived | `build_index` rebuild from corpus | RPO = n/a; RTO = index-build time |
| Eval golden set | **in git** (`sidecar/evals/`) | `git checkout` | RPO = last commit; RTO ≈ seconds |

**Key guarantee (brief requirement):** the eval golden set and the guideline
corpus are **reproducible from the repo alone** — they never live only in a
database with no recovery path. The vector index is fully rebuildable from the
committed corpus, so it needs no separate backup.

---

## 13. Interfaces & contracts (canonical)

- **HTTP (sidecar + module):** `POST /ask`, `POST /ask/stream` (Week 1, extended
  response with citations), new document-upload / extraction-status /
  evidence-retrieval / overlay-data endpoints. All specified in
  `openapi/openapi.yaml` (OpenAPI 3.0) with contract tests verifying the
  implementation matches the spec, and exercised by the Postman collection.
- **Boundary ops:** `read.php` gains `get_documents` / `get_document`
  (`ChartOperation` enum, exhaustive match); upload path is separate and guarded.
- **Typed models (`sidecar/contracts.py`):** `DocumentMetadata`,
  `DocumentContent`, `LabFact`, `IntakeFact`, `Citation`, `GuidelineChunk`,
  `RetrievalHit`, `WorkerResult` — each exports `model_json_schema()` as its
  canonical contract. Raw VLM output is validated against these before use.
- **Correlation ID** is a required header/field on every request and propagates to
  every worker, VLM call, retrieval call, and FHIR write.

---

## 14. Open sub-decisions (defaults)

- **Qdrant** (dockerized in the dev stack) over Pinecone — behind `VectorIndex`.
  *MVP uses an in-process index behind the same protocol; Qdrant is staged at plan T58.*
- **Cohere embeddings** paired with **Cohere Rerank** — single retrieval vendor,
  behind `EmbeddingClient` / `Reranker`.
- Guideline corpus = small redistributable/synthetic public snippets, in-repo.
- Critic worker deferred as extension (non-core per brief).
- SLO numeric targets fixed after the T44/T45 baseline run.
