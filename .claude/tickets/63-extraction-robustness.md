---
id: 63
title: Extraction robustness — degraded-scan envelopes, confidence tuning, missing-field matrix
status: tests-authored
depends_on: [47]
branch: ticket/63-extraction-robustness
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_extraction_robustness.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Robustness deferred from T47 (happy path assumed a clean scan). A degraded,
rotated, or noisy document makes the VLM return an imperfect envelope — a low
confidence, partially-null fact, or a malformed shape — and today the extractor
trusts it: `float(envelope["confidence"])` accepts an out-of-range number,
`list(envelope.get("unsupported_fields"))` mangles a non-list, a non-object
`fact` or a response with no text block raises deep in the code (a `TypeError` /
`StopIteration` that surfaces as a generic 502), and `unsupported_fields` is
whatever the model claimed — it can disagree with which fact values are actually
null. This ticket hardens `attach_and_extract` so a messy degraded-scan response
is handled deterministically rather than trusted or crashing.

Three changes, all in the sidecar extractor (no live VLM — the model is stubbed,
so a "degraded scan" is a stubbed imperfect envelope):

1. **Strict envelope parsing (parse, don't validate).** A new
   `ExtractionEnvelope` Pydantic model validates the whole envelope: `confidence`
   is a float in `[0, 1]`, `unsupported_fields` is a `list[str]` (default empty),
   `fact` is an object. A malformed envelope — out-of-range/non-numeric/missing
   confidence, a non-list flags value, a non-object fact — raises `ValidationError`
   (the existing 422 path), never a raw `TypeError`/`KeyError`. A response with no
   text block raises a clean `ValueError` (also 422), not `StopIteration` → 502.
2. **Confidence tuning.** A module `LOW_CONFIDENCE_THRESHOLD`; `ExtractionResult`
   gains `low_confidence: bool` (true when `confidence < threshold`), surfaced in
   `telemetry()` (still PHI-free) and in the `/extract` response so the card can
   warn the clinician to verify a low-quality scan.
3. **Authoritative missing-field reconciliation (no-invention).** `unsupported_fields`
   on the result is DERIVED from the fact's actually-null fields, so it is
   exhaustive and cannot disagree with the values (a null field is always
   reported; a populated field never is). Any field the model self-flags as
   unsupported is force-nulled first, so a low-confidence guessed value the model
   itself doubts is never surfaced.

## Acceptance criteria
- [ ] Out-of-range confidence (`1.5`, `-0.1`), non-numeric confidence (`"high"`),
  and a missing confidence key each raise `ValidationError` (→ clean 422), not a
  silently-accepted value.
- [ ] A non-object `fact` and a non-list `unsupported_fields` raise
  `ValidationError` rather than being coerced into garbage.
- [ ] A model response with no text content block raises a clean `ValueError`
  (mapped to 422), not `StopIteration`/502.
- [ ] `ExtractionResult.low_confidence` is true iff `confidence <
  LOW_CONFIDENCE_THRESHOLD`; it appears in `telemetry()` and telemetry stays
  PHI-free.
- [ ] `unsupported_fields` is derived from the actually-null fact fields:
  exhaustively, for each nullable field set to null the result flags exactly that
  field even when the model reported an empty list; a fully-grounded fact yields
  an empty list.
- [ ] A field the model lists in `unsupported_fields` is force-nulled (no invented
  value surfaced) and then appears in the derived list.
- [ ] The `/extract` response body includes `low_confidence`.
- [ ] No regression: the locked T47 extractor tests and the full sidecar suite
  stay green; strict-contract rejection (missing-required, hallucinated-extra) and
  transient-model fallover behaviour are unchanged.

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_extraction_robustness.py`:
  - envelope: out-of-range/non-numeric/missing confidence → ValidationError;
    non-object fact → ValidationError; non-list unsupported_fields → ValidationError;
    no-text-block response → ValueError.
  - confidence: low (`threshold - ε`) → `low_confidence` True; at/above threshold →
    False; `low_confidence` present in telemetry and telemetry PHI-free.
  - missing-field matrix: per nullable Lab/Intake field, null value with the model
    reporting `[]` → derived list contains exactly that field; all nullable null →
    all flagged; fully grounded → `[]`; a self-flagged valued field is force-nulled
    and flagged.
  - `/extract` response surfaces `low_confidence` (via the default extract builder).
