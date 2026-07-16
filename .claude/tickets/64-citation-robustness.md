---
id: 64
title: Citation robustness — quote-match hardening, demote-vs-block nuance
status: tests-authored
depends_on: [50]
branch: ticket/64-citation-robustness
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_citation_robustness.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Robustness deferred from T50. The `CitationGate` validates a claim's five-field
`Citation` contract and routes it record-vs-guideline, but it never checks that
the citation's `quote_or_value` is actually grounded in the cited source — a
fabricated or mismatched quote (a claim that cites a real record but quotes
something not in it) is routed as a clean grounded fact. This ticket hardens that
with an opt-in quote-grounding check whose failure action is a SOFT demote, not a
hard block — the "demote-vs-block nuance": an unverifiable quote is a grounding
weakness (downgrade the claim, keep the answer), distinct from V3's hard block for
a factual med contradiction.

Two changes, both backward-compatible:

1. **Quote-match hardening.** `CitationGate.gate(claims, sources=None)` gains an
   optional `sources` map (`source_id -> the record's searchable text`). When a
   cited claim's `source_id` is present in `sources`, the gate verifies the
   citation's `quote_or_value` is grounded in that source text — a normalized
   (case- and whitespace-insensitive) substring match in either direction, so a
   partial quote ("Warfarin" vs "Warfarin 5 mg") is grounded while a fabricated
   quote ("Aspirin" vs "Warfarin 5 mg") is not. A `source_id` absent from
   `sources` is not checked (no false demotion when the source is unavailable).
   `sources=None` (the default) preserves today's behaviour byte-for-byte.
2. **Demote-vs-block nuance.** A quote that cannot be grounded is DEMOTED (soft):
   a `quote_mismatch` flag is raised, the claim is marked with a demotion note and
   kept out of the clean record/guideline buckets, and the verdict is
   `pass_with_flags` — never `blocked`. Live wiring: `agent._apply_citation_split`
   builds `sources` from `retrieved_data` and passes it to the gate, so a
   synthesized citation is quote-checked against its own record (grounded by
   construction — no happy-path regression) and the guard is live for any future
   path that supplies a model-authored quote.

## Acceptance criteria
- [ ] `CitationGate.gate(claims)` and `gate(claims, sources=None)` are identical
  (backward compatible); existing citation-gate behaviour and tests are unchanged.
- [ ] With a `sources` map, a citation whose `quote_or_value` IS grounded in the
  cited source (normalized substring either direction) passes: routed to its
  record/guideline bucket, no flag.
- [ ] A citation whose `quote_or_value` is NOT grounded in the provided source is
  DEMOTED: a `quote_mismatch` flag (carrying the `source_id`) is raised, the claim
  is kept out of the clean buckets and marked in the rendered answer, and the
  verdict is `pass_with_flags` — NOT `blocked`.
- [ ] A `source_id` absent from `sources` is not quote-checked (no false demote).
- [ ] Quote matching is case- and whitespace-insensitive and grounds a partial
  quote in either direction; guideline citations are checked the same way.
- [ ] `agent._apply_citation_split` passes a `sources` map built from
  `retrieved_data` (keyed by ref) into `CitationGate.gate`.
- [ ] No regression: the T50 citation-gate / activation / blocked-sectioning tests
  and the full sidecar suite stay green; the VerificationGate is untouched.

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_citation_robustness.py`:
  - backward compat: `gate(claims)` == `gate(claims, sources=None)`.
  - grounded quote passes (record + guideline); case/whitespace-insensitive;
    partial either direction grounded.
  - fabricated quote → `quote_mismatch` flag, demoted (kept out of buckets),
    verdict `pass_with_flags`, not `blocked`; note present in rendered answer.
  - source_id absent from `sources` → not checked, no flag.
  - wiring: `ClaudeAgent._apply_citation_split` calls `CitationGate.gate` with a
    non-empty `sources` map derived from `retrieved_data` (spy).
