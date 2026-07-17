---
id: 53b
title: LabFact persister — procedure_order/report/result + provenance + supersede
status: todo
depends_on: [53a]
branch: ticket/53b-lab-fact-persister
base_branch: ticket/53a-derived-fact-provenance
test_command: "docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit --filter LabFactPersister'"
full_suite_command: "docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit --testsuite services --testdox'"
attempts: 0
---

## Description
Persist a validated `LabFact` (test_name, value, unit, reference_range,
collection_date, abnormal_flag, source_citation) into OpenEMR's native lab model
as a derived lab result, tracked via T53a provenance and idempotently superseded
on re-file.

`LabFactPersister` (`src/Persistence/LabFactPersister.php`) writes the three-table
OpenEMR lab structure (ProcedureService has no insert(), so compose via the
service-layer SQL/UUID helpers):
- `procedure_order` (patient_id=pid, provider_id=clinician, encounter_id=0,
  date_ordered/date_collected from collection_date, order_status='complete',
  activity=1) — one per filed lab result set.
- `procedure_report` (procedure_order_id, date_report, report_status='final',
  review_status='received', source=clinician).
- `procedure_result` (procedure_report_id, result_text=test_name, result_code=''
  or a LOINC if present, result=value, units=unit, range=reference_range,
  abnormal=mapped(abnormal_flag), result_status='final', comments=source_citation,
  document_id=source_document_id, date=collection_date). NOTE: procedure_result has
  NO procedure_type_id in this schema — the test name lives in result_text, so there
  is no procedure_type resolution.

Supersede: before writing, call
`DerivedFactProvenanceService::supersedePriorRun(pid, documentId, 'lab_result')`.
The module's lab read is ACTIVITY-BLIND (PatientSummaryService returns all results
for the patient, no activity filter), so a soft flag would not hide a re-filed lab.
Instead, for each returned prior ref DELETE the agent-created chain
(procedure_result → procedure_report → procedure_order) it points at — we only ever
delete rows the agent itself created (tracked in provenance), never user-entered
data; the superseded ai_derived_fact row preserves the audit history. After writing,
`record()` ONE provenance row per filed LabFact with target_table='procedure_order',
target_id=the new order id (the deletable unit).

Clinician user id + pid are passed in (from the T53d endpoint session), never the
wire. Abnormal-flag mapping: normalize the extracted flag to OpenEMR's
{no,yes,high,low} enum; unknown → 'no'.

## Acceptance criteria
- [ ] Filing a LabFact writes a linked procedure_order→report→result with the value/
  unit/range/abnormal/date/citation mapped to the right columns, all with uuids and
  `document_id` = source document.
- [ ] `procedure_type_id` is resolved from the test_name (reused if present, created
  if absent) so the result row satisfies its FK.
- [ ] A provenance row (fact_type='lab_result', target_table='procedure_result') is
  recorded per result.
- [ ] Re-filing the same document (new run) supersedes the prior run: prior
  procedure_order.activity flips to 0 and prior provenance rows go inactive; the new
  result is active. No duplicate active labs.
- [ ] abnormal_flag maps to {no,yes,high,low}; unknown/blank → 'no'.
- [ ] DB-backed test proves the row graph + supersede; no services-suite regression.

## Test plan (orchestrator authors these)
- DB-backed `tests/Tests/Services/AiAgent/LabFactPersisterTest.php`: file a LabFact
  → assert the three rows + provenance + the FHIR-read path
  (FhirObservationLaboratoryService) can see it; re-file → assert supersede.
- unit: abnormal-flag mapping + column mapping with a fake executor.
