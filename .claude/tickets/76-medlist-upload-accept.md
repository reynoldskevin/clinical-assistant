---
id: 76
title: med_list uploads accepted — extend DocumentUploadPolicy + widget label for the third doc type
status: todo
depends_on: [75a, 75b, 75c]
branch: ticket/76-medlist-upload-accept
base_branch: main
test_command: "docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter DocumentUploadPolicy' ; npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-medlist.test.js"
full_suite_command: "docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter AiAgent' ; npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/"
attempts: 0
---

## Description
The merged med_list document type (75a/b/c) is rejected at the upload gate: `DocumentUploadPolicy::ALLOWED` — the T62 magic-byte allow-list `upload.php` calls — enumerates only `lab_pdf` and `intake_form`, so `self::ALLOWED['med_list'] ?? []` yields an empty list and every medication-list PDF is refused with "Unsupported file type." This was caught by a live browser check on Railway (login → open patient → select Medication List → attach PDF → Upload rejected) and never by 75a/b/c's unit tests, which exercised the extractor/persister/endpoint directly and never crossed the upload gate. Medication lists are PDFs (per the "as a pdf" requirement), so `med_list` must accept `application/pdf` and reject non-PDFs exactly like `lab_pdf`. Secondarily, the extracted-facts panel mislabels a med_list extraction as "Extracted intake facts" (agent-widget.js), which should read "Extracted medications".

## Acceptance criteria
- [ ] `DocumentUploadPolicy::inspect($pdfBytes, 'med_list')` returns an AcceptedUpload with canonicalMimetype `application/pdf`.
- [ ] `DocumentUploadPolicy::inspect($pngBytes, 'med_list')` is rejected with `UploadRejectionReason::UnsupportedType` (med lists are PDF-only, like lab reports).
- [ ] The extracted-facts panel labels a `med_list` extraction "Extracted medications" (not "Extracted intake facts" or "Extracted lab result").

## Test plan (orchestrator authors these)
- unit (PHP isolated): extend DocumentUploadPolicyTest — med_list accepts PDF, rejects PNG.
- unit (JS jsdom): extend agent-widget-medlist.test.js — a med_list extraction's heading reads "Extracted medications".
