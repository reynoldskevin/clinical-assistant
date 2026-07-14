"""T46 acceptance tests (LOCKED) — document read boundary + get_documents tool.

The sidecar half of Week 2 ingestion Stage 1: the operation-dispatched HTTP
boundary gains ``get_documents`` (list this patient's documents, metadata only)
and ``get_document`` (one document's content by id), and ``build_documents_tools``
turns the boundary into the model-facing ``get_documents`` ToolSpec. Plus the
canonical ``DocumentMetadata`` / ``DocumentContent`` contracts.

No live API call and no running OpenEMR: the HTTP opener is an injected fake. The
consumer fixtures mirror the EXACT shape PatientSummaryService selects (id, name,
mimetype, docdate, doc_type for the listing — NEVER document_data; document_data
only on the single-document fetch), so a producer-side shape change breaks these.
"""
import io
import json

import pytest
from pydantic import ValidationError

from contracts import DocumentContent, DocumentMetadata, EmptyToolInput
from factory import build_chart_boundary, build_documents_tools


class _FakeResponse:
    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._buf.read()


# --- boundary methods --------------------------------------------------------

def test_get_documents_posts_op_and_pid_and_returns_array():
    captured = {}

    def opener(request, timeout=None):
        captured["method"] = request.method
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data)
        # read.php returns the provider result directly — a BARE ARRAY of
        # metadata rows for get_documents (never the document_data blob).
        return _FakeResponse(
            b'[{"id": 502, "name": "intake.pdf", "mimetype": "application/pdf",'
            b' "docdate": "2021-06-01", "doc_type": "intake_form"}]'
        )

    boundary = build_chart_boundary("http://openemr/read.php", "jwt-abc", opener=opener)
    out = boundary.get_documents(42)

    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer jwt-abc"
    assert captured["body"] == {"op": "get_documents", "pid": 42, "params": {}}
    assert out == [
        {
            "id": 502,
            "name": "intake.pdf",
            "mimetype": "application/pdf",
            "docdate": "2021-06-01",
            "doc_type": "intake_form",
        }
    ]


def test_get_document_posts_document_id_in_params_and_returns_object():
    captured = {}

    def opener(request, timeout=None):
        captured["body"] = json.loads(request.data)
        return _FakeResponse(
            b'{"id": 501, "mimetype": "application/pdf", "doc_type": "lab_pdf",'
            b' "document_data": "BASE64BLOB"}'
        )

    boundary = build_chart_boundary("http://openemr/read.php", "jwt", opener=opener)
    out = boundary.get_document(42, 501)

    assert captured["body"] == {"op": "get_document", "pid": 42, "params": {"document_id": 501}}
    assert out["document_data"] == "BASE64BLOB"


def test_get_documents_result_type_is_enforced():
    def opener(request, timeout=None):
        return _FakeResponse(b'{"not": "an array"}')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt", opener=opener)
    with pytest.raises(ValueError):
        boundary.get_documents(7)


def test_get_document_result_type_is_enforced():
    def opener(request, timeout=None):
        return _FakeResponse(b'[1, 2, 3]')

    boundary = build_chart_boundary("http://openemr/read.php", "jwt", opener=opener)
    with pytest.raises(ValueError):
        boundary.get_document(7, 1)


def test_boundary_propagates_http_errors_for_documents():
    def opener(request, timeout=None):
        raise OSError("403 Forbidden")

    boundary = build_chart_boundary("http://openemr/read.php", "bad-jwt", opener=opener)
    with pytest.raises(OSError):
        boundary.get_documents(7)


# --- get_documents ToolSpec --------------------------------------------------

def test_documents_tools_are_wellformed_and_dispatch_to_boundary():
    calls = []

    class FakeChartBoundary:
        def get_documents(self, pid):
            calls.append(("list", pid))
            # real boundary returns a list of metadata rows (validated below)
            return [{"id": 1, "name": "a.pdf", "mimetype": "application/pdf",
                     "docdate": "2021-01-01", "doc_type": "lab_pdf"}]

    tools = build_documents_tools(FakeChartBoundary())
    by_name = {t["name"]: t for t in tools}

    assert set(by_name) == {"get_documents"}
    spec = by_name["get_documents"]
    assert spec["description"]
    assert callable(spec["handler"])
    # No-argument tool: the patient is fixed for the session.
    assert spec["input_schema"] == EmptyToolInput.model_json_schema()

    out = spec["handler"](42, {})
    assert out == [{"id": 1, "name": "a.pdf", "mimetype": "application/pdf",
                    "docdate": "2021-01-01", "doc_type": "lab_pdf"}]
    assert calls == [("list", 42)]


def test_documents_tool_validates_output_against_contract():
    """A contract-violating metadata row (wrong-typed known field) must surface
    as an error via the tool handler, not pass silently."""
    class FakeChartBoundary:
        def get_documents(self, pid):
            return [{"id": "not-an-int", "name": "a.pdf"}]

    spec = build_documents_tools(FakeChartBoundary())[0]
    with pytest.raises(ValidationError):
        spec["handler"](42, {})


# --- canonical document contracts --------------------------------------------

def test_document_metadata_types_known_fields_and_ignores_extras():
    row = {
        "id": 502,
        "name": "intake.pdf",
        "mimetype": "application/pdf",
        "docdate": "2021-06-01",
        "doc_type": "intake_form",
        "some_future_field": "ignored",
    }
    meta = DocumentMetadata.model_validate(row)
    assert meta.id == 502
    assert meta.doc_type == "intake_form"


def test_document_metadata_rejects_wrong_typed_known_field():
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate({"id": "abc", "name": "x.pdf"})


def test_document_content_carries_the_blob():
    content = DocumentContent.model_validate(
        {"id": 501, "mimetype": "application/pdf", "doc_type": "lab_pdf",
         "document_data": "BASE64BLOB", "extra": "ignored"}
    )
    assert content.id == 501
    assert content.document_data == "BASE64BLOB"
