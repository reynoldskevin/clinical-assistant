"""``get_intake_form`` tool — bridge the intake extractor into the /ask agent.

``get_documents`` lists intake-form *metadata* only, and no other /ask tool can
read a document's contents, so the co-pilot could not answer questions about what
a patient reported on their intake form ("I don't have the text of the concern").
``build_intake_tool`` closes that gap: it resolves the patient's intake form
pid-scoped through the same read boundary the upload-time extractor uses, runs the
VLM extractor, and returns each grounded field as its own citable row.

Unit tests only: the chart boundary and the VLM message-creator are injected
fakes — no anthropic SDK, no live API call, no running OpenEMR.
"""
import json
from types import SimpleNamespace

import pytest

from contracts import GetIntakeFactInput
from factory import build_intake_tool


# --- fakes -------------------------------------------------------------------

def _resp(envelope):
    text = SimpleNamespace(type="text", text=json.dumps(envelope))
    return SimpleNamespace(content=[text], stop_reason="end_turn")


_INTAKE_ENVELOPE = {
    "confidence": 0.9,
    "unsupported_fields": ["allergies"],
    "fact": {
        "demographics": "F, 54, DOB 1967-02-11",
        "chief_concern": "follow-up for elevated blood sugar",
        "current_medications": "metformin 500mg BID",
        "allergies": None,
        "family_history": "father — type 2 diabetes",
        "source_citation": "intake form, section 2",
    },
}


class FakeBoundary:
    """Fake chart boundary: get_documents lists metadata, get_document the blob."""

    def __init__(self, documents, doc=None):
        self._documents = documents
        self._doc = doc or {
            "id": 502,
            "mimetype": "image/png",
            "doc_type": "intake_form",
            "document_data": "aW50YWtlIHBuZw==",
        }
        self.document_calls = []

    def get_documents(self, pid):
        return self._documents

    def get_document(self, pid, document_id):
        self.document_calls.append((pid, document_id))
        return self._doc


def _vlm(envelope=_INTAKE_ENVELOPE):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return _resp(envelope)

    create.calls = calls  # type: ignore[attr-defined]
    return create


_INTAKE_META = {
    "id": 502, "name": "intake.png", "mimetype": "image/png",
    "docdate": "2021-06-01", "doc_type": "intake_form",
}
_LAB_META = {
    "id": 501, "name": "lab.pdf", "mimetype": "application/pdf",
    "docdate": "2021-03-20", "doc_type": "lab_pdf",
}


# --- ToolSpec shape ----------------------------------------------------------

def test_intake_tool_is_wellformed():
    spec = build_intake_tool(FakeBoundary([_INTAKE_META]), _vlm())
    assert spec["name"] == "get_intake_form"
    assert spec["description"]
    assert callable(spec["handler"])
    # optional document_id, unknown fields rejected
    assert spec["input_schema"] == GetIntakeFactInput.model_json_schema()


# --- happy path: grounded, citable rows --------------------------------------

def test_extracts_intake_form_as_citable_rows():
    boundary = FakeBoundary([_INTAKE_META])
    spec = build_intake_tool(boundary, _vlm())

    rows = spec["handler"](42, {})

    # the newest intake form was fetched pid-scoped and extracted
    assert boundary.document_calls == [(42, 502)]

    by_field = {r["title"]: r for r in rows}
    # chief_concern surfaces first and is grounded with a citable ref + value
    assert rows[0]["title"] == "chief_concern"
    assert by_field["chief_concern"]["ref"] == "intake:502:chief_concern"
    assert by_field["chief_concern"]["value"] == "follow-up for elevated blood sugar"
    assert by_field["chief_concern"]["section"] == "intake form, section 2"
    # every returned row carries the ref the citation gate needs to ground it
    assert all(r["ref"].startswith("intake:502:") for r in rows)


def test_ungroundable_field_is_dropped_not_invented():
    # allergies came back null (flagged unsupported); it must not appear as a row
    spec = build_intake_tool(FakeBoundary([_INTAKE_META]), _vlm())
    rows = spec["handler"](42, {})
    assert "allergies" not in {r["title"] for r in rows}


# --- document resolution -----------------------------------------------------

def test_picks_the_most_recent_intake_form_ignoring_labs():
    # get_documents is newest-first; a lab PDF ahead of the intake form must be
    # skipped so the tool always extracts an intake form, not the lab.
    boundary = FakeBoundary([_LAB_META, _INTAKE_META])
    spec = build_intake_tool(boundary, _vlm())

    spec["handler"](42, {})
    assert boundary.document_calls == [(42, 502)]


def test_explicit_document_id_targets_that_form():
    older = {**_INTAKE_META, "id": 400, "docdate": "2020-01-01"}
    boundary = FakeBoundary([_INTAKE_META, older])
    spec = build_intake_tool(boundary, _vlm())

    spec["handler"](42, {"document_id": 400})
    assert boundary.document_calls == [(42, 400)]


def test_no_intake_form_returns_empty_list():
    # only a lab on file: an empty result the model reads as "not documented",
    # never a fabricated concern.
    boundary = FakeBoundary([_LAB_META])
    spec = build_intake_tool(boundary, _vlm())
    assert spec["handler"](42, {}) == []
    assert boundary.document_calls == []


def test_unknown_document_id_returns_empty_list():
    boundary = FakeBoundary([_INTAKE_META])
    spec = build_intake_tool(boundary, _vlm())
    assert spec["handler"](42, {"document_id": 999}) == []
    assert boundary.document_calls == []


# --- input contract ----------------------------------------------------------

def test_input_rejects_unknown_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GetIntakeFactInput.model_validate({"doc_id": 5})
