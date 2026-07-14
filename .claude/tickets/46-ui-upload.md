---
id: 46
title: UI file upload + document read boundary (get_documents/get_document)
status: ready-for-merge
depends_on: []
branch: ticket/46-ui-upload
base_branch: main
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 vendor/bin/phpunit -c phpunit-isolated.xml --filter 'ChartReadServiceDocumentsTest|ChartReadEndpointDocumentsTest' ; docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_documents_tools.py -q"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 vendor/bin/phpunit -c phpunit-isolated.xml ; docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 2
---

## Description
Week 2 Stage 1, requirement 1 (ingest). Give the AI Clinical Co-Pilot a way to bring a lab PDF or intake form into the chart and read it back through the existing pid-scoped, audited JWT boundary. The physician/front-desk selects a file on the card, picks its doc_type (lab_pdf | intake_form), and the browser POSTs it to a guarded module endpoint that stores the source blob in OpenEMR's `documents` table via OpenEMR's own document storage. Two new read operations — `get_documents` (list this patient's documents, metadata only) and `get_document` (one document's content by id) — are added to the boundary, so the sidecar can fetch a stored document back through the same fail-closed, cross-pid-403 boundary. VLM extraction is NOT in scope (that is T47); this ticket only stores and reads documents. Happy path only: assume a valid PDF/image of reasonable size (idempotency, type/size rejection, error UX deferred to T62).

## Acceptance criteria
- [ ] `ChartOperation` gains `GetDocuments = 'get_documents'` and `GetDocument = 'get_document'` (the enum stays the boundary whitelist; exhaustive match, no default).
- [ ] `ChartReadProviderInterface` gains `getDocuments(int $pid): array` (list of metadata rows) and `getDocument(int $pid, int $documentId): array` (one document incl. content, or [] when it is not this patient's).
- [ ] `PatientSummaryService` implements both, pid-scoped over `documents` (foreign_id = pid, deleted = 0). `getDocuments` returns metadata only (id, name, mimetype, docdate, doc_type/category) and NEVER the `document_data` blob. `getDocument` returns a foreign document (another patient's id) as [] — pid scope is the security boundary.
- [ ] `ChartReadEndpoint` dispatches both ops (pid from the verified token; `document_id` from params for get_document); a cross-pid / invalid / expired token reads NO document for either op (fail closed).
- [ ] New guarded upload endpoint `public/upload.php`: interactive-session + CSRF authenticated (NOT $ignoreAuth — this is a logged-in clinician action), pid-scoped; receives the multipart file + doc_type; stores the blob as one `documents` row for that pid via OpenEMR's document storage. Reads/writes audited; correlation id forwarded where applicable; no raw document text in logs.
- [ ] The card (`card.html.twig` + `agent-widget.js`) offers a file-select + doc_type control that POSTs to the upload endpoint and reflects success/failure.
- [ ] Sidecar: `DocumentMetadata` + `DocumentContent` Pydantic contracts in `contracts.py`; `ChartBoundary.get_documents(pid)` / `.get_document(pid, document_id)`; a `get_documents` ToolSpec (list, no args) wired via `build_documents_tools`. A contract test pins the EXACT read.php↔boundary JSON shape for both new ops (shared fixture, decision #12).
- [ ] No behaviour regression: full PHP isolated suite (minus the known RSA-key pre-existing failure) and full sidecar suite green.

## Test plan (orchestrator authors these)
- PHP unit `tests/Tests/Isolated/Modules/AiAgent/Boundary/ChartReadEndpointDocumentsTest.php`: fake provider; GetDocuments dispatches with token pid; GetDocument passes `document_id` param + token pid; cross-pid + expired token → InvalidScopedTokenException, no provider call, for both ops.
- PHP unit `tests/Tests/Isolated/Modules/AiAgent/Boundary/ChartOperationTest.php` (extend the existing file is LOCKED — instead assert new cases in the endpoint test / a small case-presence test): the two new enum cases exist and `tryFrom` maps their wire strings.
- PHP DB-backed isolated `tests/Tests/Isolated/Modules/AiAgent/Service/ChartReadServiceDocumentsTest.php`: seed `documents` rows for pid 1 and pid 2; `getDocuments(1)` returns only pid-1 rows, metadata only (no `document_data` key); `getDocument(1, ownId)` returns content; `getDocument(1, pid2DocId)` → []; `getDocument(1, 999)` → [].
- Sidecar unit `sidecar/tests/test_contracts.py` (extend): `DocumentMetadata` (id, name, mimetype, docdate, doc_type — extra ignored, wrong-typed known raises) + `DocumentContent` (id, mimetype, content/url).
- Sidecar unit `sidecar/tests/test_documents_tools.py`: `ChartBoundary.get_documents/get_document` POST the right op/params (fake opener), enforce object/array result types; `build_documents_tools` returns a `get_documents` ToolSpec whose input_schema == EmptyToolInput schema; **contract test** — one recorded read.php-shaped payload consumed by the boundary parser (producer shape ⇄ consumer parser).
- Selenium smoke (orchestrator-run verification, not a locked test, per Week 1 precedent): drive the card via Panther to upload a synthetic file and confirm one `documents` row + `get_documents` lists it; screenshot.
