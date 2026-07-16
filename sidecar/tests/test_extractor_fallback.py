"""Extractor model-fallover: a transient overload on the primary model must fail
over to a secondary, not fail the whole extraction.

An overloaded vision tier (HTTP 529) was failing otherwise-valid upload
extractions because the extractor made a single call to one model. The fix tries
``model`` first and, only on a transient availability error, each of
``fallback_models`` in order. A non-transient error and a contract ValidationError
propagate unchanged — a fallover must never mask a real failure.

Unit tests only: the VLM message-creator is a fake dispatching on the ``model``
kwarg; no anthropic SDK import, no live API call.
"""
import base64
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from extractor import _is_transient_error, attach_and_extract


_INTAKE_DOC = {
    "id": 502,
    "mimetype": "image/png",
    "doc_type": "intake_form",
    "document_data": base64.b64encode(b"intake png bytes").decode("ascii"),
}

_VALID_INTAKE = {
    "confidence": 0.99,
    "unsupported_fields": [],
    "fact": {
        "demographics": "Jordan Rivera; DOB 1968-03-12; Female",
        "chief_concern": "Chest tightness for 2 weeks.",
        "current_medications": "Lisinopril 10 mg daily",
        "allergies": "Penicillin",
        "family_history": "Father: MI at 60",
        "source_citation": "Intake form, chief concern section.",
    },
}


class _Overloaded(Exception):
    """Stand-in for anthropic.OverloadedError (a 529), matched by status_code."""

    status_code = 529


class _BadRequest(Exception):
    """A non-transient error (no transient status / name) — must NOT fail over."""


class FakeBoundary:
    def get_document(self, pid, document_id):
        return _INTAKE_DOC


class ByModelVlm:
    """A fake message-creator that dispatches on the ``model`` kwarg.

    Each behavior is either an exception instance (raised) or an envelope
    dict/str (returned as an SDK-shaped Message). Records the models it saw.
    """

    def __init__(self, behaviors):
        self._behaviors = behaviors
        self.models_called = []

    def __call__(self, **kwargs):
        model = kwargs["model"]
        self.models_called.append(model)
        behavior = self._behaviors[model]
        if isinstance(behavior, Exception):
            raise behavior
        body = behavior if isinstance(behavior, str) else json.dumps(behavior)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=body)], stop_reason="end_turn")


def _extract(vlm, **kw):
    return attach_and_extract(
        1, 502, "intake_form", chart_boundary=FakeBoundary(), message_creator=vlm, **kw
    )


# --- transient-error classification -------------------------------------------

def test_is_transient_error_by_status_code():
    assert _is_transient_error(_Overloaded()) is True


def test_is_transient_error_by_class_name():
    class RateLimitError(Exception):
        pass

    assert _is_transient_error(RateLimitError()) is True


def test_non_transient_error_is_not_flagged():
    assert _is_transient_error(_BadRequest()) is False
    assert _is_transient_error(ValueError("nope")) is False


# --- fallover behavior --------------------------------------------------------

def test_falls_over_to_secondary_on_overload():
    vlm = ByModelVlm({"primary": _Overloaded(), "sonnet": _VALID_INTAKE})
    result = _extract(vlm, model="primary", fallback_models=("sonnet",))
    assert result.fact.chief_concern == "Chest tightness for 2 weeks."
    # Primary was tried, then the fallback — in order.
    assert vlm.models_called == ["primary", "sonnet"]


def test_walks_multiple_fallbacks_until_one_succeeds():
    vlm = ByModelVlm({"primary": _Overloaded(), "mid": _Overloaded(), "sonnet": _VALID_INTAKE})
    result = _extract(vlm, model="primary", fallback_models=("mid", "sonnet"))
    assert result.confidence == 0.99
    assert vlm.models_called == ["primary", "mid", "sonnet"]


def test_no_fallover_on_non_transient_error():
    vlm = ByModelVlm({"primary": _BadRequest("bad"), "sonnet": _VALID_INTAKE})
    with pytest.raises(_BadRequest):
        _extract(vlm, model="primary", fallback_models=("sonnet",))
    assert vlm.models_called == ["primary"]  # never fell over


def test_validation_error_propagates_without_fallover():
    # Primary responds (call succeeds) but the envelope is contract-invalid: the
    # ValidationError is raised AFTER the call loop, so no fallover is attempted.
    invalid = {"confidence": 0.9, "unsupported_fields": [], "fact": {"chief_concern": "x"}}
    vlm = ByModelVlm({"primary": invalid, "sonnet": _VALID_INTAKE})
    with pytest.raises(ValidationError):
        _extract(vlm, model="primary", fallback_models=("sonnet",))
    assert vlm.models_called == ["primary"]


def test_transient_on_last_model_propagates():
    # Overload with no fallback left must surface (becomes a 502 upstream), not hang.
    vlm = ByModelVlm({"primary": _Overloaded()})
    with pytest.raises(_Overloaded):
        _extract(vlm, model="primary", fallback_models=())
    assert vlm.models_called == ["primary"]
