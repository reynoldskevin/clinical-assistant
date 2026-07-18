# W2_SCHEMAS — Extraction schemas for `lab_pdf` and `intake_form`

The Week-2 document-ingestion pipeline turns a scanned lab PDF or a front-desk
intake form into **strict, validated, cited structured facts**. The Pydantic
models below are the **single source of truth**: raw VLM output is validated
against them *before any downstream use* and never bypasses the contract. Both
carry a mandatory **source-citation** field so every extracted fact is grounded.

- **Definitions:** [`sidecar/contracts.py`](sidecar/contracts.py) (`LabFact`,
  `IntakeFact`, `ExtractionEnvelope`).
- **Producer:** [`sidecar/extractor.py`](sidecar/extractor.py)
  (`attach_and_extract` → validated `ExtractionResult`).
- **Validation tests:**
  [`sidecar/tests/test_schema_citation_contract.py`](sidecar/tests/test_schema_citation_contract.py)
  (focused, 16 cases — all green), plus `test_extractor.py`,
  `test_extraction_robustness.py`, and `test_contracts.py`.

> **Why Pydantic, not Zod.** The extractor and the whole sidecar are Python, and
> the schema must be enforced *server-side at the extraction boundary* — the one
> place raw model output enters the system. Pydantic v2 is that enforcement
> point; each model also exports `model_json_schema()` as a language-neutral
> JSON-Schema contract (shown below), which is exactly what a Zod (or any other)
> client would mirror. There is no browser-side extraction path that would need
> Zod — the card only renders the already-validated fact.

---

## Design rules (both schemas)

1. **Strict** (`extra="forbid"`) — the VLM cannot smuggle unknown fields past the
   contract; an unexpected key raises `ValidationError`.
2. **Every named field is a required *key*** — typed `Optional[str]` with **no
   default**. A field the model cannot ground is explicitly `null` (and surfaced
   via `unsupported_fields`), never omitted, never invented.
3. **`source_citation` is required, non-null, and non-empty** (`Field(min_length=1)`).
   Grounding is mandatory; an empty citation is rejected.
4. **Confidence is advisory; quote-locatability is authoritative.** The envelope
   carries a `[0,1]` confidence, but a field is only trusted when its quote can be
   located on the page (drives the bbox overlay and the gate).

---

## `LabFact` — `doc_type = "lab_pdf"`

A single lab result extracted from a laboratory report.

| Field | Type | Required key | Nullable | Notes |
|---|---|---|---|---|
| `test_name` | `str` | yes | yes | e.g. "HbA1c" |
| `value` | `str` | yes | yes | kept as a string — never coerced |
| `unit` | `str` | yes | yes | e.g. "%" |
| `reference_range` | `str` | yes | yes | e.g. "4.0–5.6" |
| `collection_date` | `str` | yes | yes | as printed on the report |
| `abnormal_flag` | `str` | yes | yes | e.g. "H" / "L" |
| **`source_citation`** | `str` | **yes** | **no** | **`min_length=1`** — where on the page the result came from |

## `IntakeFact` — `doc_type = "intake_form"`

Structured facts extracted from a patient intake form. Each field is one flat,
human-readable string (multi-part values combined with `'; '`).

| Field | Type | Required key | Nullable | Notes |
|---|---|---|---|---|
| `demographics` | `str` | yes | yes | name / DOB / sex / contact as applicable |
| `chief_concern` | `str` | yes | yes | reason for visit |
| `current_medications` | `str` | yes | yes | one string, `'; '`-separated |
| `allergies` | `str` | yes | yes | |
| `family_history` | `str` | yes | yes | |
| **`source_citation`** | `str` | **yes** | **no** | **`min_length=1`** — section of the form the facts came from |

*(`MedicationListFact` for `doc_type = "med_list"` follows the same rules: a
single `medications` string + a mandatory `source_citation`.)*

## `ExtractionEnvelope` — what the VLM returns

The raw model output is parsed into this envelope **strictly first** (`strict=True`),
then `fact` is validated against the doc-type contract:

```json
{ "confidence": 0.0-1.0, "unsupported_fields": ["field", ...], "fact": { ... } }
```

`confidence` out of `[0,1]`, a non-list `unsupported_fields`, or a non-object
`fact` each raise `ValidationError`. Fields the model flags unsupported are
force-nulled in `fact` *before* validation, and `unsupported_fields` is then
**re-derived from the validated fact** (every field except `source_citation`
whose value is null), so the flag can never disagree with the actual values.

---

## Canonical JSON-Schema contract (exported)

Each model's `model_json_schema()` is the language-neutral contract. Abbreviated
for `LabFact` (every property is `{"anyOf":[{"type":"string"},{"type":"null"}]}`
except the citation):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["test_name","value","unit","reference_range",
               "collection_date","abnormal_flag","source_citation"],
  "properties": {
    "test_name":        {"anyOf": [{"type":"string"},{"type":"null"}]},
    "value":            {"anyOf": [{"type":"string"},{"type":"null"}]},
    "unit":             {"anyOf": [{"type":"string"},{"type":"null"}]},
    "reference_range":  {"anyOf": [{"type":"string"},{"type":"null"}]},
    "collection_date":  {"anyOf": [{"type":"string"},{"type":"null"}]},
    "abnormal_flag":    {"anyOf": [{"type":"string"},{"type":"null"}]},
    "source_citation":  {"type": "string", "minLength": 1}
  }
}
```

The test suite asserts exactly this: `source_citation` is in `required`, has
`minLength: 1`, and `additionalProperties` is `false` — for **both** `LabFact`
and `IntakeFact`.

---

## Validation coverage (what the tests prove)

`test_schema_citation_contract.py` — **16 cases, all green**:

- a fully-grounded lab result / intake form validates;
- **missing / null / empty `source_citation` is rejected** (grounding mandatory);
- a groundable-but-absent field may be `null` (never invented), citation intact;
- every named field is a required key (dropping any one raises);
- unknown fields are rejected (`extra="forbid"`);
- the exported JSON schema marks `source_citation` required + `minLength: 1` +
  `additionalProperties: false`.

Reproduce:

```bash
docker exec w2-sidecar-test bash -lc \
  'cd /repo/sidecar && python -m pytest tests/test_schema_citation_contract.py -q'
# or on host with sidecar deps:
python -m pytest -c sidecar/pytest.ini sidecar/tests/test_schema_citation_contract.py
```

The broader extraction path (schema-as-source-of-truth raises, no-invention
reconciliation, transient-model fallover) is covered by `test_extractor.py` and
`test_extraction_robustness.py`.
