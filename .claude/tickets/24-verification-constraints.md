---
id: 024
title: Verification gate — constraints (V3 contradiction + V6 patient-scope); V4/V5 deferred
status: ready-for-merge    # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [023]
branch: ticket/24-verification-constraints
base_branch: ticket/23-verification-grounding   # STACKED off T23 (unmerged) — shares verification.py/agent.py; see skill decision #2
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Extend the verification gate (ARCHITECTURE.md §5) with the two deterministic
**blocking** constraints: V3 (contradiction — a cited med/allergy must actually be
that record) and V6 (patient scope — no leaked identifiers). A blocked verdict
replaces the draft with a safe fallback. V4 (physiologic ranges) and V5 (order/dose
classifier) are DEFERRED — they need clinical sign-off (exact ranges / a validated
order-dose classifier), so they are documented as not-yet-implemented, not guessed.

## Design (`verification.py`, extends the T23 gate)

- `verify(draft, citations, retrieved_refs, retrieved_data=None) -> verdict`. `retrieved_data`
  maps `ref -> record` (the tool row, e.g. `{"drug": "Warfarin", ...}`) for the refs seen this turn.
- **V3 (contradiction):** for each citation to a med/allergy ref (`prescription:` / `list:`) whose
  record is in `retrieved_data`, the record's drug/title name must appear (fuzzy: case-insensitive,
  token overlap) in the SENTENCE carrying that `[Sn]`. A citation whose sentence names a DIFFERENT
  drug (e.g. "on Aspirin [S1]" where S1 → Warfarin) → flag `contradicts_record` and **BLOCK**
  (fabricated/misattributed med or allergy is dangerous).
- **V6 (patient scope):** the answer must not leak raw identifiers — block on an SSN pattern
  (`\d{3}-\d{2}-\d{4}`) or an `MRN`/`medical record number` label followed by digits → flag
  `out_of_scope_phi` and **BLOCK**. (Conservative reading of §5's "no identifiers of any patient
  other than the scoped one": a chart-summary answer never needs to emit a raw MRN/SSN.)
- **Verdict precedence:** any blocking flag (V3/V6) → verdict `blocked`, and `rendered_answer`
  becomes a SAFE FALLBACK ("I can't verify that against the record.") — the unverified draft is
  never shown. Otherwise V1/V2's `pass`/`pass_with_flags` behaviour is unchanged.
- **Agent:** collect `retrieved_data` (ref → record) alongside `retrieved_refs` and pass it to the
  gate. Blocked answers return the safe fallback (and store it in multi-turn history).
- **V4/V5:** not implemented — documented deferred (clinical sign-off). No silent stub.

## Acceptance criteria
- [ ] V3: a cited med whose name matches the record → no contradiction. A cited med/allergy whose sentence names a different drug than the record → `contradicts_record` flag + verdict `blocked`.
- [ ] V6: an answer containing an SSN pattern or `MRN <digits>` → `out_of_scope_phi` flag + verdict `blocked`; a clean answer is not blocked.
- [ ] A blocked verdict yields the safe-fallback `rendered_answer` (never the unverified draft); blocking takes precedence over `pass_with_flags`.
- [ ] V1/V2 behaviour from T23 is unchanged when nothing blocks.
- [ ] Agent passes `retrieved_data` to the gate; a blocked formatted answer returns the safe fallback; format-less answers still pass through unchanged.
- [ ] All prior sidecar tests still pass.
- [ ] **MR carries `Depends on: !40` — merge T23 first** (stacked).

## Test plan (LOCKED — authored)
- `test_verification_constraints.py`: V3 match→ok / mismatch→blocked; med vs non-med refs; V6 SSN + MRN block, clean pass; block precedence + safe-fallback text; V1/V2 unaffected when nothing blocks; agent passes retrieved_data + returns the fallback on a blocked formatted answer.
