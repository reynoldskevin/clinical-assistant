---
id: 50
title: Citation contract on every claim + record/evidence split in verification gate
status: tests-authored
depends_on: [49]
branch: ticket/50-citation-gate
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_citation_gate.py tests/test_verification.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Every clinical claim in the final answer carries a machine-readable citation `{source_type, source_id, page_or_section, field_or_chunk_id, quote_or_value}`. Extend the Week 1 verification gate so an uncited claim is demoted/blocked, and the response separates patient-record facts from guideline evidence (distinct sections/markers). Prerequisite for the `citation_present` rubric. Happy path (quote-match robustness / demote-vs-block tuning → T64).

## Acceptance criteria
- [ ] Citation contract type with the five fields; every clinical claim carries one.
- [ ] Gate demotes/blocks a claim with no citation.
- [ ] Final answer separates record facts from guideline evidence (distinct sections/markers).
- [ ] Week 1 verification regression cases still green.

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_citation_gate.py`: uncited clinical claim blocked/demoted; cited claim passes; record vs evidence split asserted; citation contract shape validated.

## Design (contract the locked tests pin — implementer builds to this)
New module `sidecar/citation_gate.py` (composes with, does not modify, the W1
`VerificationGate`; the W1 `test_verification*.py` suite is the regression guard):

- `Citation` (Pydantic, `extra="forbid"`) — the five required, non-empty (`min_length=1`)
  fields: `source_type`, `source_id`, `page_or_section`, `field_or_chunk_id`,
  `quote_or_value`. `Citation.model_fields` is exactly those five.
- Module constants: `SOURCE_RECORD="record"`, `SOURCE_GUIDELINE="guideline"`,
  `RECORD_SECTION_HEADER`, `GUIDELINE_SECTION_HEADER` (distinct), `DEMOTION_NOTE`.
- `CitationGate().gate(claims)` where each claim is `{"text": str, "citation": <dict|Citation|None>}`.
  A dict citation is validated through `Citation` (malformed → `ValidationError`).
  Returns `{"verdict", "flags", "record_facts": list[str], "guideline_evidence": list[str],
  "rendered_answer": str}`:
  - cited claims route by `source_type` into `record_facts` / `guideline_evidence`;
  - an uncited claim (`citation is None`) raises an `uncited_claim` flag, is demoted
    (marked with `DEMOTION_NOTE`), and is NOT emitted as a clean grounded fact;
  - `verdict`: `"pass"` (no flags) / `"pass_with_flags"` (demotions) / `"blocked"`;
  - `rendered_answer` separates the two kinds under the distinct section headers,
    record section before guideline section.
