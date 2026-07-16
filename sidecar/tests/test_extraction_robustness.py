"""T63 acceptance tests (LOCKED) — extraction robustness.

Deferred from T47 (happy path assumed a clean scan). A degraded / rotated / noisy
document makes the VLM return an imperfect envelope: a low confidence, a partially
null fact, a self-contradicting flag list, or a malformed shape. The extractor
must handle these deterministically rather than trust them or crash:

* the whole envelope is parsed strictly — out-of-range/non-numeric/missing
  confidence, a non-list `unsupported_fields`, or a non-object `fact` raise
  ValidationError (the existing 422 path), and a response with NO text block
  raises a clean ValueError (not StopIteration -> 502);
* a `low_confidence` flag (threshold `LOW_CONFIDENCE_THRESHOLD`) is surfaced on
  the result, in PHI-free telemetry, and in the `/extract` response;
* `unsupported_fields` is DERIVED from the actually-null fact fields (exhaustive,
  cannot disagree with the values), and a model-self-flagged field is force-nulled
  so a doubted guess is never surfaced (no invention).

Unit tests only: the VLM message-creator and chart boundary are injected fakes —
no anthropic SDK, no live API, no running OpenEMR.
"""
import base64
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from extractor import LOW_CONFIDENCE_THRESHOLD, attach_and_extract


# --- fakes (mirror tests/test_extractor.py) ----------------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _resp(text):
    return SimpleNamespace(content=[_text(text)], stop_reason="end_turn")


class ScriptedVlm:
    """A fake message-creator returning one scripted JSON envelope."""

    def __init__(self, envelope):
        self._body = json.dumps(envelope) if not isinstance(envelope, str) else envelope
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _resp(self._body)


class RawVlm:
    """A fake message-creator returning an arbitrary caller-supplied response."""

    def __init__(self, response):
        self._response = response

    def __call__(self, **kwargs):
        return self._response


class FakeBoundary:
    def __init__(self, doc):
        self._doc = doc

    def get_document(self, pid, document_id):
        return self._doc


_LAB_DOC = {
    "id": 501,
    "mimetype": "application/pdf",
    "doc_type": "lab_pdf",
    "document_data": base64.b64encode(b"%PDF-1.4 synthetic lab").decode("ascii"),
}
_INTAKE_DOC = {
    "id": 502,
    "mimetype": "image/png",
    "doc_type": "intake_form",
    "document_data": base64.b64encode(b"intake png bytes").decode("ascii"),
}

_LAB_NULLABLE = [
    "test_name", "value", "unit", "reference_range", "collection_date", "abnormal_flag",
]
_INTAKE_NULLABLE = [
    "demographics", "chief_concern", "current_medications", "allergies", "family_history",
]


def _lab_fact(**over):
    fact = {
        "test_name": "Hemoglobin A1c",
        "value": "7.2",
        "unit": "%",
        "reference_range": "4.0-5.6",
        "collection_date": "2021-03-20",
        "abnormal_flag": "H",
        "source_citation": "page 1, results table row 3",
    }
    fact.update(over)
    return fact


def _intake_fact(**over):
    fact = {
        "demographics": "F, 54, DOB 1967-02-11",
        "chief_concern": "follow-up for elevated blood sugar",
        "current_medications": "metformin 500mg BID",
        "allergies": "penicillin",
        "family_history": "father — type 2 diabetes",
        "source_citation": "intake form, section 2",
    }
    fact.update(over)
    return fact


def _extract_lab(envelope):
    return attach_and_extract(
        1, 501, "lab_pdf",
        chart_boundary=FakeBoundary(_LAB_DOC),
        message_creator=ScriptedVlm(envelope),
    )


def _extract_intake(envelope):
    return attach_and_extract(
        1, 502, "intake_form",
        chart_boundary=FakeBoundary(_INTAKE_DOC),
        message_creator=ScriptedVlm(envelope),
    )


# --- envelope robustness (a degraded scan yields a messy envelope) -----------

@pytest.mark.parametrize("bad_confidence", [1.5, -0.1, "high", "", None])
def test_invalid_confidence_is_rejected(bad_confidence):
    with pytest.raises(ValidationError):
        _extract_lab({"confidence": bad_confidence, "unsupported_fields": [], "fact": _lab_fact()})


def test_missing_confidence_is_rejected():
    with pytest.raises(ValidationError):
        _extract_lab({"unsupported_fields": [], "fact": _lab_fact()})


def test_non_object_fact_is_rejected():
    with pytest.raises(ValidationError):
        _extract_lab({"confidence": 0.9, "unsupported_fields": [], "fact": "not an object"})


def test_non_list_unsupported_fields_is_rejected():
    # A bare string must NOT be coerced into a per-character list.
    with pytest.raises(ValidationError):
        _extract_lab({"confidence": 0.9, "unsupported_fields": "unit", "fact": _lab_fact()})


def test_response_with_no_text_block_raises_clean_valueerror():
    # A degraded/odd model response with no text content block must surface a clean
    # ValueError (mapped to 422), never a StopIteration that becomes a generic 502.
    resp = SimpleNamespace(content=[SimpleNamespace(type="image")], stop_reason="end_turn")
    with pytest.raises(ValueError):
        attach_and_extract(
            1, 501, "lab_pdf",
            chart_boundary=FakeBoundary(_LAB_DOC),
            message_creator=RawVlm(resp),
        )


# --- confidence tuning -------------------------------------------------------

def test_low_confidence_scan_is_flagged():
    result = _extract_lab({
        "confidence": LOW_CONFIDENCE_THRESHOLD - 0.01,
        "unsupported_fields": [],
        "fact": _lab_fact(),
    })
    assert result.low_confidence is True


def test_at_or_above_threshold_is_not_low_confidence():
    at = _extract_lab({"confidence": LOW_CONFIDENCE_THRESHOLD, "unsupported_fields": [], "fact": _lab_fact()})
    above = _extract_lab({"confidence": 0.99, "unsupported_fields": [], "fact": _lab_fact()})
    assert at.low_confidence is False
    assert above.low_confidence is False


def test_low_confidence_in_telemetry_and_phi_free():
    result = _extract_lab({
        "confidence": LOW_CONFIDENCE_THRESHOLD - 0.05,
        "unsupported_fields": [],
        "fact": _lab_fact(),
    })
    tele = result.telemetry()
    assert tele["low_confidence"] is True
    blob = json.dumps(tele)
    for phi in ("Hemoglobin", "7.2", "2021-03-20", _LAB_DOC["document_data"]):
        assert phi not in blob


# --- authoritative missing-field reconciliation (no invention) ---------------

@pytest.mark.parametrize("field", _LAB_NULLABLE)
def test_null_lab_field_is_flagged_even_when_model_underreports(field):
    # The model reports an EMPTY unsupported list but leaves the value null; the
    # derived list is authoritative and must still flag the field.
    result = _extract_lab({
        "confidence": 0.9,
        "unsupported_fields": [],
        "fact": _lab_fact(**{field: None}),
    })
    assert field in result.unsupported_fields
    assert getattr(result.fact, field) is None


@pytest.mark.parametrize("field", _INTAKE_NULLABLE)
def test_null_intake_field_is_flagged_even_when_model_underreports(field):
    result = _extract_intake({
        "confidence": 0.9,
        "unsupported_fields": [],
        "fact": _intake_fact(**{field: None}),
    })
    assert field in result.unsupported_fields


def test_fully_grounded_fact_has_empty_unsupported():
    result = _extract_lab({"confidence": 0.97, "unsupported_fields": [], "fact": _lab_fact()})
    assert result.unsupported_fields == []


def test_all_nullable_fields_null_flags_all():
    nulls = {f: None for f in _LAB_NULLABLE}
    result = _extract_lab({"confidence": 0.2, "unsupported_fields": [], "fact": _lab_fact(**nulls)})
    assert sorted(result.unsupported_fields) == sorted(_LAB_NULLABLE)


def test_self_flagged_valued_field_is_forced_null_no_invention():
    # The model contradicts itself: it flags `unit` as unsupported yet still returns
    # a value for it. Trust the flag — the doubted value must NOT be surfaced.
    result = _extract_lab({
        "confidence": 0.4,
        "unsupported_fields": ["unit"],
        "fact": _lab_fact(unit="mg/dL"),
    })
    assert result.fact.unit is None
    assert "unit" in result.unsupported_fields


def test_source_citation_is_never_reported_unsupported():
    result = _extract_lab({"confidence": 0.9, "unsupported_fields": [], "fact": _lab_fact()})
    assert "source_citation" not in result.unsupported_fields


# --- /extract response surfaces the low-confidence flag ----------------------

def test_extract_response_surfaces_low_confidence(monkeypatch):
    import server

    monkeypatch.setattr(server, "build_chart_boundary", lambda *a, **k: FakeBoundary(_LAB_DOC))
    vlm = ScriptedVlm({
        "confidence": LOW_CONFIDENCE_THRESHOLD - 0.05,
        "unsupported_fields": [],
        "fact": _lab_fact(),
    })
    extract = server.default_extract_builder("http://openemr/summary.php", vlm)

    out = extract(1, "jwt-token", 501, "lab_pdf")

    assert out["ok"] is True
    assert out["low_confidence"] is True
