---
id: 53d
title: Clinician-gated persist.php endpoint + "Accept & file to chart" card UI
status: ready-for-merge
depends_on: [53c]
branch: ticket/53d-persist-endpoint-ui
base_branch: main
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-persist.test.js ; docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter PersistFactsEndpoint'"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent ; docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit --testsuite services --testdox'"
attempts: 0
---

## Description
Expose T53b/T53c behind an interactive, clinician-authenticated action — the agent
PROPOSES extracted facts; the clinician COMMITS them. Mirrors upload.php's gate.

1. **`public/persist.php`** — interactive endpoint (NOT the read-only JWT boundary):
   `require globals.php` (authenticated session), verify CSRF, ACL gate via
   `ClinicalAccessPolicy::mayReadClinical`, pid FROM SESSION (never wire). Body:
   `{ source_document_id, extraction_run_id, doc_type, fact }` (the same validated
   fact envelope the card already holds from /extract). Dispatch: doc_type
   'lab_pdf' → LabFactPersister; 'intake_form' → IntakeFactPersister; pass the
   session clinician id + pid. Returns `{ ok, filed: [{fact_type, count}], superseded: N }`.
   Never leak internal detail; generic errors only. Re-file is safe (supersede).
2. **Card UI (agent-widget.js)** — on the extracted-facts panel, an **"Accept &
   file to chart"** button. On click: POST the held fact envelope + document id +
   extraction_run_id (correlation_id from /extract) + csrf to persist.php; disable
   while in flight; on success show a confirmation ("Filed N facts to the chart.")
   and mark the panel filed; on failure a safe inline message. The button is hidden
   when identity_check flags a wrong-chart mismatch (don't invite filing to the
   wrong chart) unless the clinician dismisses — default hidden on mismatch.
   All DOM via createElement/textContent (no innerHTML).

## Acceptance criteria
- [x] persist.php denies unauthenticated/invalid-CSRF/unauthorized/no-pid requests
  with safe 4xx and writes nothing; pid comes only from the session.
- [x] A valid lab request routes to LabFactPersister; a valid intake request to
  IntakeFactPersister; the response reports filed fact_types + counts + superseded.
- [x] Re-posting the same document supersedes rather than duplicates (delegated to
  the persisters).
- [x] The card shows an "Accept & file to chart" button on extracted facts, POSTs
  the held envelope with the document id + extraction_run_id + csrf, disables while
  in flight, and shows a safe success/failure message; no innerHTML.
- [x] On a wrong-chart identity mismatch the file button is hidden by default.
- [x] No regression: module jest suite + services suite stay green.

## Test plan (orchestrator authors these)
- jsdom `tests/agent-widget-persist.test.js`: button present on facts panel; click
  POSTs to persist.php with the right body (document id, extraction_run_id, csrf,
  fact) and disables; success renders the confirmation; hidden on identity mismatch.
- endpoint (isolated/contract): a request-parsing unit test for persist.php's
  auth/pid-from-session/dispatch shape (mirror the upload.php test style), and a
  contract test pinning the exact JSON body the card sends == what persist.php parses.
