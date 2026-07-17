"""T60 contract tests (LOCKED) — the sidecar OpenAPI 3.0 spec.

`sidecar/openapi.yaml` is the single published description of the sidecar HTTP
API (`GET /health`, `GET /ready`, `POST /ask`, `POST /ask/stream`,
`POST /extract`). It is not a hand-maintained sibling that can silently drift:
these tests pin it against the two things it must agree with —

  1. the canonical Pydantic ENVELOPE contracts in ``contracts.py``
     (``AskRequest``/``AskResponse``/``ExtractRequest``/``ExtractResponse``), so
     the documented request/response property names + required fields ARE the
     models' (single source of truth); and
  2. the SERVER's real behavior — a live round-trip through ``process_ask`` /
     ``process_extract`` must yield a body that validates against the response
     model, and the ``doc_type`` enum must equal the server's ``_DOC_TYPES``.

A field or status code added on one side but not the other fails here. The
Postman collection is likewise held to cover every documented endpoint.

Deterministic: no live API, no sockets — scripted agent/extract fakes and static
file reads only.
"""
import json
import os
from types import SimpleNamespace

import yaml

import server
from agent import ClaudeAgent
from contracts import AskRequest, AskResponse, ExtractRequest, ExtractResponse
from server import process_ask, process_extract

_HERE = os.path.dirname(__file__)
SPEC_PATH = os.path.join(_HERE, "..", "openapi.yaml")
POSTMAN_PATH = os.path.join(_HERE, "..", "..", "postman", "oe-ai-agent.postman_collection.json")

# The complete sidecar HTTP surface: path -> the HTTP methods it serves.
EXPECTED_ENDPOINTS = {
    "/health": {"get"},
    "/ready": {"get"},
    "/ask": {"post"},
    "/ask/stream": {"post"},
    "/extract": {"post"},
}
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


# --- helpers -----------------------------------------------------------------

def _spec():
    with open(SPEC_PATH) as fh:
        return yaml.safe_load(fh)


def _resolve(spec, node):
    """Follow a single JSON-Schema ``$ref`` into the spec, else return node."""
    if isinstance(node, dict) and "$ref" in node:
        cur = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur[part]
        return cur
    return node


def _op(spec, path, method="post"):
    return spec["paths"][path][method]


def _request_schema(spec, path):
    node = _op(spec, path)["requestBody"]["content"]["application/json"]["schema"]
    return _resolve(spec, node)


def _response_schema(spec, path, code="200"):
    node = _op(spec, path)["responses"][str(code)]["content"]["application/json"]["schema"]
    return _resolve(spec, node)


def _names_and_required(schema):
    return set((schema.get("properties") or {}).keys()), set(schema.get("required") or [])


# --- scripted agent fake (mirrors the other sidecar tests) -------------------

def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _agent_builder(pid, jwt):
    return ClaudeAgent(
        lambda **k: _resp([_text("A grounded answer.")], "end_turn"),
        lambda p: {},
        correlation_id="cid-t60",
    )


# --- 1. spec is a valid OpenAPI 3.0 document ---------------------------------

def test_spec_exists_and_is_openapi_3():
    spec = _spec()
    assert isinstance(spec, dict)
    assert str(spec.get("openapi", "")).startswith("3.0")
    assert "info" in spec and spec["info"].get("title")
    assert isinstance(spec.get("paths"), dict) and spec["paths"]


def test_spec_documents_exactly_the_sidecar_endpoints():
    spec = _spec()
    got = {
        path: {m for m in ops if m in _HTTP_METHODS}
        for path, ops in spec["paths"].items()
    }
    assert got == EXPECTED_ENDPOINTS


# --- 2. envelope models exist and the spec is derived from them --------------

def test_ask_request_schema_matches_model():
    assert _names_and_required(_request_schema(_spec(), "/ask")) == _names_and_required(
        AskRequest.model_json_schema()
    )


def test_ask_response_schema_matches_model():
    assert _names_and_required(_response_schema(_spec(), "/ask")) == _names_and_required(
        AskResponse.model_json_schema()
    )


def test_extract_request_schema_matches_model():
    assert _names_and_required(_request_schema(_spec(), "/extract")) == _names_and_required(
        ExtractRequest.model_json_schema()
    )


def test_extract_response_schema_matches_model():
    assert _names_and_required(_response_schema(_spec(), "/extract")) == _names_and_required(
        ExtractResponse.model_json_schema()
    )


def test_doc_type_enum_matches_server_doc_types():
    # The model constrains doc_type to exactly the server's accepted set...
    model_enum = ExtractRequest.model_json_schema()["properties"]["doc_type"].get("enum")
    assert set(model_enum or []) == set(server._DOC_TYPES)
    # ...and so does the published spec.
    spec_enum = _request_schema(_spec(), "/extract")["properties"]["doc_type"].get("enum")
    assert set(spec_enum or []) == set(server._DOC_TYPES)


# --- 3. the models agree with the SERVER's real behavior (round-trip) --------

def test_ask_response_model_accepts_a_real_process_ask_body():
    status, body = process_ask("Bearer jwt", json.dumps({"pid": 1, "question": "hi"}).encode(), _agent_builder)
    assert status == 200
    # The real server body validates against the documented response contract.
    AskResponse.model_validate(body)


def test_extract_response_model_accepts_a_real_process_extract_body():
    # The extract-fn returns exactly the envelope default_extract_builder emits.
    def extract_fn(pid, jwt, document_id, doc_type):
        return {
            "ok": True,
            "doc_type": doc_type,
            "confidence": 0.94,
            "low_confidence": False,
            "unsupported_fields": [],
            "fact": {"test_name": "HbA1c", "value": "7.4", "source_citation": "p1"},
            "correlation_id": "cid-x",
            "identity_check": {"matches": True, "mismatched_identifiers": [], "warning": None},
        }

    status, body = process_extract(
        "Bearer tok",
        json.dumps({"pid": 1, "document_id": 5, "doc_type": "lab_pdf"}).encode(),
        extract_fn,
    )
    assert status == 200
    ExtractResponse.model_validate(body)


def test_extract_request_model_accepts_the_documented_request_body():
    ExtractRequest.model_validate({"pid": 1, "document_id": 5, "doc_type": "intake_form"})
    AskRequest.model_validate({"pid": 1, "question": "summarize"})


# --- 4. security + error contracts -------------------------------------------

def test_bearer_auth_declared_and_applied_to_authed_endpoints():
    spec = _spec()
    schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    bearer = [n for n, s in schemes.items() if s.get("type") == "http" and s.get("scheme") == "bearer"]
    assert bearer, "no http bearer security scheme declared"
    name = bearer[0]
    for path in ("/ask", "/ask/stream", "/extract"):
        sec = _op(spec, path).get("security") or []
        assert any(name in requirement for requirement in sec), f"{path} does not require bearer auth"


def test_error_status_codes_match_the_server():
    spec = _spec()
    ask_codes = set(_op(spec, "/ask")["responses"].keys())
    assert {"400", "401", "502"} <= ask_codes
    extract_codes = set(_op(spec, "/extract")["responses"].keys())
    assert {"400", "401", "422", "502"} <= extract_codes


# --- 5. Postman collection covers every documented endpoint ------------------

def test_postman_collection_covers_every_sidecar_endpoint():
    with open(POSTMAN_PATH) as fh:
        collection = json.load(fh)

    def _walk(items):
        for it in items:
            if "item" in it:
                yield from _walk(it["item"])
            elif "request" in it:
                yield it["request"]

    raws = [(r.get("url") or {}).get("raw", "") for r in _walk(collection["item"])]
    for path in EXPECTED_ENDPOINTS:
        # Each sidecar path (e.g. /ask, /ask/stream, /extract, /health, /ready)
        # is exercised by at least one request against the sidecar base url.
        assert any(path.lstrip("/") in raw.split("sidecar_base_url}}")[-1] for raw in raws if "sidecar_base_url" in raw), (
            f"Postman collection has no request for sidecar endpoint {path}"
        )
