---
id: 060
title: OpenAPI 3.0 spec + contract tests + updated Postman collection
status: ready-for-merge
depends_on: [54]
branch: ticket/60-openapi-contract-tests
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_openapi_spec.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Publish a single canonical OpenAPI 3.0 description of the sidecar HTTP API (`GET /health`, `GET /ready`, `POST /ask`, `POST /ask/stream`, `POST /extract`) at `sidecar/openapi.yaml`, backed by canonical Pydantic request/response envelope contracts in `contracts.py` (`AskRequest`, `AskResponse`, `ExtractRequest`, `ExtractResponse` — the T54 residual folded in here) so the spec is derived from one source of truth rather than hand-drifted. Contract tests pin the spec against both the envelope models and the server's real behavior (a round-trip through `process_ask`/`process_extract`), so a field or status added on one side but not the other fails CI. The Postman collection is updated to cover `/extract` (currently missing) so it matches the spec.

## Acceptance criteria
- [ ] `sidecar/openapi.yaml` exists and is a structurally-valid OpenAPI 3.0 document (`openapi: 3.0.x`, `info`, `paths`).
- [ ] Every sidecar endpoint + method is documented, and only those: `GET /health`, `GET /ready`, `POST /ask`, `POST /ask/stream`, `POST /extract`.
- [ ] `contracts.py` defines `AskRequest`, `AskResponse`, `ExtractRequest`, `ExtractResponse`; `ExtractRequest.doc_type` is constrained to the server's `_DOC_TYPES` (`lab_pdf`, `intake_form`).
- [ ] The spec's request/response component schemas are derived from those models — the documented property names and required fields for `/ask` and `/extract` match `model_json_schema()`.
- [ ] The models match the server: a real round-trip through `process_ask` (fake agent) yields a body that validates against `AskResponse`; through `process_extract` (fake extract-fn) yields one that validates against `ExtractResponse`.
- [ ] Bearer auth is declared (`components.securitySchemes`, type `http`/`bearer`) and applied to `/ask`, `/ask/stream`, `/extract`.
- [ ] Documented error responses match the server: `/ask` → 400/401/502; `/extract` → 400/401/422/502.
- [ ] The Postman collection (`postman/oe-ai-agent.postman_collection.json`) has a request for every sidecar endpoint the spec documents, including `/extract`.

## Test plan (orchestrator authors these)
- contract: `sidecar/tests/test_openapi_spec.py` — spec validity/coverage, spec⇄model schema agreement, model⇄server round-trip, security + error-code documentation, Postman coverage.
