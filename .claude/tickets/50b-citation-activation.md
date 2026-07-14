---
id: 50b
title: Activation — surface T50 structured citations + record/evidence split in the live Co-Pilot answer
status: ready-for-merge
depends_on: [50]
branch: ticket/50b-citation-activation
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_citation_activation.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Activation step (mirrors T49b, which wired the evidence_retriever into the running agent). T50 built `CitationGate` + the 5-field `Citation` contract as a unit-tested module, but nothing imports it — the live `/ask` answer still renders the Week-1 way (inline `[Sn]` markers + a stripped `{n, ref}` citations block through `VerificationGate` only). This ticket makes the T50 gate visible in the RUNNING Co-Pilot: after the existing W1 grounding gate runs, the surviving cited claims are lifted into structured `Citation`s and run through `CitationGate`, so the answer returned by `_gate_final_answer` separates **patient-record facts** from **guideline evidence** under distinct section markers, and any clinical claim left without a resolvable citation is demoted. Because guideline evidence rows are today un-`ref`'d (T48's `evidence_retriever` returns `{citation, text, score}` with no `ref`), this ticket also gives those rows a citable `guideline:<chunk_id>` ref so a guideline claim can carry an `[Sn]` marker and be routed to the evidence section. The prompt is nudged so the model uses the `guideline:` ref prefix for corpus citations. The card renders the two sections. Scope is the RAG-vs-record split on the single-turn `/ask` + `stream_ask` path (both share `default_agent_builder`); quote-match robustness and demote-vs-block tuning stay deferred to T64. Happy path.

## Acceptance criteria
- [ ] `agent._gate_final_answer` composes `CitationGate` after `VerificationGate`: a gated answer whose surviving claims cite record refs AND guideline refs is returned split into a patient-record section and a guideline-evidence section under the distinct T50 section headers, record section first.
- [ ] Each surviving `[Sn]` citation is mapped to a structured `Citation` (all five fields populated from the turn's `retrieved_data`): `source_type` is `guideline` when the ref is a `guideline:` ref, else `record`; `source_id` = the ref; `quote_or_value` derived from the record/chunk; the mapping never invents fields (a ref with no backing record is treated as uncited → demoted, not fabricated).
- [ ] `build_evidence_retriever_tool` rows carry a `ref` of the form `guideline:<chunk_id>` (in addition to the existing `citation`/`text`/`score`), so `_collect_refs`/`_collect_data` capture guideline evidence and the gate can ground a guideline `[Sn]`. Existing T48/T49b retrieval tests still green (extra key, nothing removed).
- [ ] The system prompt instructs the model to cite guideline evidence with the `guideline:` ref prefix (record refs unchanged), so record vs guideline is derivable from the ref.
- [ ] A format-less answer (no citations block) and a record-only answer both still render correctly — the record/guideline split degrades to a single section (or no header) when there is no guideline evidence, and W1 back-compat answers are unchanged.
- [ ] The verification regression (`test_verification*.py`) and the T50 gate tests stay green; the pid-scoped boundary is unaffected; `stream_ask` inherits the behaviour via the shared builder.
- [ ] The card (`agent-widget.js`) renders the two section headers as headings (markdown `##` support in the safe-DOM renderer, or an equivalent visual separator) — text-node/createElement only, never `innerHTML`.

## Test plan (orchestrator authors these)
- integration `sidecar/tests/test_citation_activation.py`:
  - a `ScriptedCreator` turn where the model calls `get_medications` (record) and `evidence_retriever` (guideline) and emits a final answer with `[S1]` on a med claim + `[S2]` on a guideline claim + a `{n, ref}` citations block → `agent.run(...)` returns text containing BOTH T50 section headers with the med claim under the record section and the guideline claim under the guideline evidence section, record header before guideline header;
  - the `evidence_retriever` handler output includes a `ref` starting `guideline:` and that ref appears in the turn's `retrieved_refs` (so a guideline `[Sn]` is grounded, not stripped as fabricated);
  - a claim citing a ref with no backing record is demoted (T50 `uncited_claim` / not-grounded), not shown as a clean fact;
  - a format-less answer (no citations block) is returned unchanged (W1 back-compat);
  - contract test: an evidence row serialized by the tool is accepted by `_collect_refs`/`_collect_data` AND the citation-mapping bridge produces a valid `Citation` from it (real producer → real consumer, no hand-faked shape).
- JS: a small assertion (or documented manual Selenium check) that the widget renders the two section headers as headers without `innerHTML`.

## Design (bridge approach — implementer builds to the locked tests)
- **Do not change the model's citation contract shape** (`[Sn]` + `{n, ref}` block) — bridge from it. In `_gate_final_answer`, after `VerificationGate.verify(...)` returns its `rendered_answer` + surviving citations, build a `list[Claim]` for `CitationGate`: one claim per sentence carrying a surviving `[Sn]`, each with a `Citation` synthesized from `retrieved_data[ref]` (prefix → `source_type`, ref → `source_id`, section/field/quote from the record row or guideline chunk). Sentences with no surviving marker are non-clinical prose and pass through unsectioned.
- **Guideline refs:** give `evidence_retriever` rows `ref="guideline:" + chunk_id`; register the chunk text as the `quote_or_value` source in `retrieved_data`. This is the one change that makes guideline claims groundable at all.
- **Rendering:** `CitationGate.rendered_answer` already emits the two section headers; return that from `_gate_final_answer`. The widget gains `##`-heading support in its existing safe markdown path.

## Deferred (explicit follow-ups, NOT this ticket)
- Citation quote-match robustness + demote-vs-block nuance tuning → T64.
- PDF bounding-box visual overlay of a citation on the source document → T56.
- Wiring the T49 supervisor graph into `process_ask`/`stream_ask` (separate activation, needs SSE/multi-turn reconciliation) → its own ticket.
