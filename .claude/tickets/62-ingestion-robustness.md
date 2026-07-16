---
id: 62
title: Ingestion robustness — invalid-type/oversized rejection, content-hash idempotency, upload error UX
status: ready-for-merge
depends_on: [46]
branch: ticket/62-ingestion-robustness
base_branch: main
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 vendor/bin/phpunit -c phpunit-isolated.xml --filter 'DocumentUploadPolicyTest|DocumentDedupServiceTest'"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 vendor/bin/phpunit -c phpunit-isolated.xml ; docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Robustness deferred from T46 (which was happy-path only: "idempotency, type/size
rejection, error UX deferred to T62"). Hardens the guarded upload endpoint
(`public/upload.php`) and the card upload UX without changing the T46 storage
path or read boundary.

Three additions, each fail-closed:

1. **Invalid-type / oversized rejection.** New pure `DocumentUploadPolicy`
   (`src/Ingestion/`) identifies the file by its OWN magic bytes — never the
   browser-declared Content-Type, which the client controls and can spoof —
   enforces a per-doc_type allow-list (lab report → PDF; intake form → PDF, PNG,
   or JPEG) and a 10 MiB size cap, and hands back the sniffed canonical mimetype
   for storage. A refusal throws a typed `UploadRejected` carrying a
   `UploadRejectionReason` (empty → 400, too-large → 413, unsupported → 415),
   each owning a safe, specific user message.
2. **Content-hash idempotency.** New pid-scoped
   `PatientSummaryService::findDocumentIdByHash()` looks the patient up by the
   sha3-512 that `\Document::createDocument()` already records for every stored
   blob. Re-posting identical bytes to the same chart resolves to the existing
   document id (`duplicate: true`) instead of storing a second copy; the same
   bytes on another chart stay distinct (pid is the scope). The dedup + store are
   one guarded block so a DB fault fails closed.
3. **Upload error UX.** `agent-widget.js` now parses the JSON body on any status
   and surfaces the endpoint's specific message (invalid type / too large) rather
   than a generic failure, and shows a distinct "already on file" state for a
   duplicate (still auto-extracting from the existing document). Messages are
   written via textContent (never HTML).

## Acceptance criteria
- [x] Upload sniffs content by magic number and rejects a type outside the
  per-doc_type allow-list (e.g. an image posted as a lab_pdf, or a content-type
  spoof) with a 415 + specific message — the browser Content-Type is not trusted.
- [x] An oversized file is rejected (413) and an empty one (400) before storage.
- [x] Re-uploading identical bytes to the same chart returns the existing id with
  `duplicate: true` and stores no second row; the same bytes on a different chart
  are a distinct document; deleted rows never count as a duplicate.
- [x] The card shows the endpoint's specific rejection message and a distinct
  duplicate state; the happy-path confirmation is unchanged.
- [x] No behaviour regression: full PHP isolated suite green (minus the two
  pre-existing environmental failures — the RSA-key permission notice and the
  ai-agent card Twig-loader-path compile test, both failing identically on clean
  main); sidecar suite untouched. All changed PHP is PHPStan level-10 clean and
  phpcs/eslint clean.

## Test plan
- PHP unit `tests/Tests/Isolated/Modules/AiAgent/Ingestion/DocumentUploadPolicyTest.php`:
  accepts PDF for lab_pdf and PDF/PNG/JPEG for intake_form (canonical mimetype);
  rejects image-as-lab_pdf, content-type spoof, text-as-pdf (UnsupportedType),
  empty (EmptyFile), oversized (TooLarge); accepts exactly at the cap; each reason
  maps to its 4xx status + non-empty message.
- PHP DB-backed isolated `tests/Tests/Isolated/Modules/AiAgent/Service/DocumentDedupServiceTest.php`:
  `findDocumentIdByHash` returns the existing id for same pid+hash, null for an
  unknown hash, is patient-scoped, and ignores deleted rows.
- Live Selenium smoke (orchestrator-run, not a locked test): authenticated upload
  against pid 1 — first PDF → 200/new id; identical bytes → 200 same id + `duplicate:true`;
  PNG-as-lab_pdf → 415 + specific message. Verified end-to-end.
