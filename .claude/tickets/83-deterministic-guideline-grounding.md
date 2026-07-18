---
id: 83
title: Deterministically ground inline guideline citations into citation_sources
status: tests-authored
depends_on: []
branch: ticket/83-deterministic-guideline-grounding
base_branch: main
test_command: "docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python -m pytest tests/test_guideline_grounding.py -q'"
full_suite_command: "docker exec w2-sidecar-test bash -lc 'cd /repo && python -m pytest -c sidecar/pytest.ini sidecar/tests'"
attempts: 0
---

## Description
Guideline-evidence citations render as chips only intermittently because grounding depends on the model's citation *formatting*. The `evidence_retriever` tool returns rows keyed `ref: "guideline:<chunk_id>"`, but a guideline reaches the card's `citation_sources` map only when the model declares it in the fenced ```citations block with an `[Sn]` number (`build_citation_sources` keys by marker number). The system prompt also permits the model to simply inline the raw `[guideline:<ref>]` marker — and when it does, the ref never enters `citation_sources`, so the answer carries an unresolved raw tag (which the widget then strips) and the guideline citation is lost. Same question, different run → chip or no chip. This ticket makes grounding deterministic: after gating, every inline `[guideline:<ref>]` marker whose ref was actually retrieved this turn (`ref ∈ retrieved_refs`, backed by `retrieved_data`) is resolved into `citation_sources` keyed by that exact ref (type `guideline`), independent of whether the model declared it in the citations block. A cited guideline ref that was NOT retrieved is never added (no fabrication). The result is deterministic: given the model's answer text and the turn's retrieved data, `citation_sources` is a pure function of them, so a retrieved+cited guideline is ALWAYS a chip.

## Acceptance criteria
- [ ] AC1 — After a turn whose final answer inlines `[guideline:<ref>]` for a ref present in `retrieved_data` (from evidence_retriever), `agent.citation_sources[<ref>]` exists, keyed by the EXACT ref string, with `type == "guideline"`, `section` = the chunk's citation title, and `text` = the chunk's snippet — EVEN WHEN the model's fenced ```citations block does not declare that ref.
- [ ] AC2 — An inline `[guideline:<ref>]` marker whose ref was NOT retrieved this turn is NOT added to `citation_sources` (no fabricated source).
- [ ] AC3 — Determinism: two identical turns (same scripted model output + same retrieved data) produce equal `citation_sources` dicts.
- [ ] AC4 — No regression: a record `[Sn]` citation declared in the ```citations block still populates `citation_sources` (keyed by `str(n)`, `type == "record"`) alongside a resolved inline guideline entry.
- [ ] AC5 — The resolved guideline key equals the inline marker's bracket content (so the shipped widget, which looks a guideline marker up by its ref key, renders it as a `[Gk]` chip).

## Test plan (orchestrator authors these; LOCKED)
- py (new `sidecar/tests/test_guideline_grounding.py`): drive the REAL `ClaudeAgent` with a scripted message-creator (a tool_use round that calls an injected fake `evidence_retriever` returning `{ref:"guideline:...", citation, text, score}` rows, then a final text answer that inlines a `[guideline:<ref>]` marker with an EMPTY / non-declaring ```citations block). Assert `agent.citation_sources` gains the guideline entry keyed by ref with the right type/section/text (AC1, AC5); an inline ref not in the retrieved rows is absent (AC2); two runs are equal (AC3); and a declared record `[Sn]` still lands keyed by number, type record, next to the resolved guideline (AC4). Deterministic/offline: scripted model, fake tool + boundary, no SDK, no network, no key.
