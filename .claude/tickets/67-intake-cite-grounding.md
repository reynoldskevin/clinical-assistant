---
id: 67
title: Intake/tool-fact verification — intake-tool citations are grounded record evidence
status: ready-for-merge
depends_on: [50]
branch: ticket/67-intake-cite-grounding
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_intake_grounding.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
T67 was filed 2026-07-15 reporting that the verification gate hedged
`get_intake_form` facts as "(not supported by the record)" *even when correctly
cited* `[Sn]` — the premise being that the verifier treated only structured chart
reads as "the record" and not tool-derived intake facts.

**Investigation finding: the described bug does not reproduce at HEAD; it is
already resolved.** The `VerificationGate` never discriminated citations by ref
*source*. V2 grounds any sentence whose `[Sn]` marker resolves to a ref that was
retrieved this turn, and intake rows carry a citable `intake:<document_id>:<field>`
ref that flows into `retrieved_refs` exactly like a chart ref (wired by `7fa9e39`).
The citation split (`_citation_for`) already routes any non-`guideline:` ref —
intake included — to the record side. The live symptom (an intake numeric sentence
the model left *uncited*, or with the `[Sn]` marker placed after the terminal
period, getting demoted) was fixed at the prompt layer by `1acceca` (require a
marker on every dated/numeric sentence) and `e368ad9` (resolve a bare "concern" to
the intake chief_concern) — both landed after the ticket was filed.

Per CLAUDE.md ("fix at the source, not the sink"), adding an intake-specific
exception to the gate would be the *wrong* fix: an uncited numeric intake claim is
genuinely ungrounded and V2 must still flag it. So this ticket closes T67 as
**already resolved** and adds a regression guard so the resolved behavior cannot
silently regress. No production code changes.

Also folds in an intake-fixture change surfaced during the extract-model work:
a second **matching** fixture (`synthetic_intake_form_match.png`, identity =
seeded pid 1: Brett333 Cruickshank494 / 1925-06-24 / Female) for clean
intake-grounding demos, kept SEPARATE from the existing **mismatch** fixture
(`synthetic_intake_form.png`) that the wrong-chart safety demo (`e9c17a3`,
`uc_wrong_chart.yaml` live sweep) depends on. The generator now emits both variants
from one shared clinical body with resilient font lookup.

## Acceptance criteria
- [x] A correctly-cited intake fact (`intake:<doc>:<field>` ref) passes V1/V2 clean
  with no "(not supported by the record)" hedge — pure gate and end-to-end agent.
- [x] The citation split routes an intake fact to the RECORD side, never the
  guideline side (no spurious `## Guideline evidence` section).
- [x] An *uncited* numeric intake sentence is still demoted — the guard proves the
  fix does not special-case / weaken V2.
- [x] Two intake fixtures exist and are distinct: match (pid 1) and mismatch; the
  wrong-chart fixture is left byte-for-byte unchanged.
- [x] Full sidecar suite green (403 passed, 2 skipped).

## Test plan
- unit + integration `sidecar/tests/test_intake_grounding.py`:
  - pure gate: cited intake numeric fact → `pass`, no flags, no hedge;
  - pure gate: uncited intake numeric fact → `pass_with_flags`, `ungrounded_claim`,
    hedge present (V2 not weakened);
  - end-to-end: scripted turn calls a stub `get_intake_form` returning the real
    `{ref,title,section,value}` row shape, drafts a cited answer → final answer is
    grounded (no hedge, `[Sn]` survives), record-only (no guideline split header).
