---
id: 023
title: Verification gate — grounding (V1 citation-validity, V2 claim-grounding)
status: tests-authored     # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [022]
branch: ticket/23-verification-grounding
base_branch: main          # T22 merged; branch off main
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

A grounding gate that runs on the draft answer before it reaches the clinician
(ARCHITECTURE.md §4–§5): V1 citation validity + V2 claim grounding. Fabricated
citations are stripped; numeric clinical assertions with no valid citation are
demoted to "not supported by the record". The gate is deterministic and testable;
the agent applies it to answers that use the §4 grounding format.

## Design

- **`verification.py` — `VerificationGate.verify(draft, citations, retrieved_refs) -> verdict`**
  (pure, deterministic). `citations` = `[{"n": int, "ref": str}]`; `retrieved_refs` = the
  refs tools returned this turn. Returns the §5.2 schema `{verdict, flags, rendered_answer}`.
  - **V1 (citation validity):** a citation whose `ref` ∉ `retrieved_refs ∪ {"openemr:_absence"}`
    is fabricated → flag `fabricated_citation` (action `stripped`); remove its `[Sn]` markers
    from the rendered text and drop the citation.
  - **V2 (claim grounding):** a sentence that is a *numeric clinical assertion* (documented
    crude heuristic: contains a digit) but carries NO valid `[Sn]` marker → flag
    `ungrounded_claim` (action `demoted`); append " (not supported by the record)" to it.
  - **Verdict:** `pass` (no flags) or `pass_with_flags`. V1/V2 never `block` — blocking is
    V5/V6 (T24). `rendered_answer` is the transformed text (markers stripped/sentences demoted).
  - Documented limits (§5.3): the digit heuristic misses non-numeric assertions (meds/problems —
    V3 in T24 covers those); the gate is only as strong as its constraint set.
- **`agent.py` — apply the gate on the final answer** ONLY when the model used the §4 format:
  the model is prompted (system prompt) to emit `[Sn]` markers + a trailing fenced
  ```citations JSON block. On the final turn, if that block is present, parse it →
  (display_text, citations), collect `retrieved_refs` from tool-result `ref` fields seen this
  turn, run the gate, and return `rendered_answer` (the citations block removed). If NO
  citations block is present (legacy / unformatted answers), return the draft UNCHANGED —
  so T12/T17/T21/T22's format-less tests stay green. Applies in `run_turn` (multi-turn history
  stores the rendered answer).

## Acceptance criteria
- [ ] `verify` returns `{verdict, flags, rendered_answer}`; `pass` when everything is grounded.
- [ ] V1: a fabricated citation (ref not retrieved, not `_absence`) → its `[Sn]` markers stripped from `rendered_answer`, a `fabricated_citation` flag, verdict `pass_with_flags`.
- [ ] V2: a numeric assertion sentence with no valid `[Sn]` → demoted (" (not supported by the record)"), an `ungrounded_claim` flag, `pass_with_flags`.
- [ ] `openemr:_absence` is a VALID citation ref (verified negatives are not fabricated).
- [ ] Non-assertion sentences (no digit) and grounded numeric sentences (digit + valid `[Sn]`) produce no flags.
- [ ] Agent: a final answer using the §4 format is gated (fabricated stripped, ungrounded demoted, the citations block removed from the returned text); an answer WITHOUT the format is returned unchanged (back-compat — existing tests green).
- [ ] All prior sidecar tests still pass.

## Test plan (LOCKED — authored)
- `test_verification.py`: gate V1/V2 matrix (pass, fabricated-stripped, ungrounded-demoted, _absence valid, non-assertion ok, verdict/flag schema) + agent integration (formatted answer gated; unformatted answer passes through).
