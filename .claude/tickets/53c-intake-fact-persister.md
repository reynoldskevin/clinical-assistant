---
id: 53c
title: IntakeFact persister — split narrative fields → meds/allergies/conditions/note
status: todo
depends_on: [53a]
branch: ticket/53c-intake-fact-persister
base_branch: main
test_command: "docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter \"IntakeFactPersister|NarrativeFieldSplitter\"'"
full_suite_command: "docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit --testsuite services --testdox'"
attempts: 0
---

## Description
Persist a validated `IntakeFact` into discrete OpenEMR clinical records, tracked
via T53a provenance and idempotently superseded on re-file. IntakeFact fields are
NARRATIVE strings, so a deterministic splitter (`NarrativeFieldSplitter`) breaks
each on `;` and newlines into line-items (NOT commas — a dosage like "10 mg, twice
daily" must stay intact); each line-item is filed as one record
with its text as the title/drug (demo-grade, fully traceable — NOT clinical NLP).
Empty/`—`/"none"/"no known …" items are skipped.

`IntakeFactPersister` (`src/Persistence/IntakeFactPersister.php`) writes via raw
prepared-statement SQL on the injected \PDO (the OpenEMR service classes need the
full app bootstrap, unavailable in the module's isolated harness — so mirror
PatientSummaryService/LabFactPersister's raw-SQL style, same as those services'
tables):
- `current_medications` → split → `prescriptions` rows (patient_id=pid, drug=line,
  active=1, start_date=today, txDate/usage_category_title/request_intent_title
  supplied for strict mode, provider_id=createdBy). fact_type='medication',
  target_table='prescriptions'.
- `allergies` → split → `lists` type='allergy' (pid, title=line, activity=1).
  fact_type='allergy', target_table='lists'. "NKDA"/"no known" → skip.
- `family_history` → split → `lists` type='medical_problem' (pid, title=line,
  activity=1). fact_type='family_history', target_table='lists'.
- `chief_concern` → ONE `pnotes` row (pid, title='AI intake: chief concern',
  body=text, activity=1). fact_type='chief_concern', target_table='pnotes'. Not split.
- `demographics` → NOT written (identity is the chart's own; used only by the
  T68 wrong-chart check). Skipped by design.

Per fact_type, supersede prior run first
(`supersedePriorRun(pid, documentId, factType)`), then SOFT-DEACTIVATE each returned
prior target (the module reads meds/allergies/problems WHERE active/activity=1, so a
soft flag hides them — unlike labs): prescriptions.active=0 / lists.activity=0 /
pnotes.activity=0. Then insert the new line-items and `record()` a provenance row each. Services that take `puuid` get it by resolving
pid→uuid. Clinician id + pid passed in from the T53d endpoint.

## Acceptance criteria
- [ ] `NarrativeFieldSplitter` splits on `;` and newlines, trims, drops empty and
  negation sentinels ("none", "no known drug allergies", "NKDA", "—"), and is
  unit-tested across representative intake strings.
- [ ] current_medications line-items become active `prescriptions` rows;
  allergies become `lists` type='allergy'; family_history becomes `lists`
  type='medical_problem'; chief_concern becomes one note/observation.
- [ ] demographics is never written.
- [ ] Each written record gets a provenance row with the correct fact_type +
  target_table; re-filing supersedes the prior run per fact_type (old records
  deactivated, new active), no duplicates.
- [ ] Services requiring puuid receive a correctly resolved patient uuid.
- [ ] DB-backed test proves each mapping + supersede; no services-suite regression.

## Test plan (orchestrator authors these)
- unit: `NarrativeFieldSplitter` cases (multi-med, negations, blanks, ragged
  punctuation).
- DB-backed `tests/Tests/Services/AiAgent/IntakeFactPersisterTest.php`: file an
  IntakeFact → assert prescriptions/allergy-list/problem-list/note rows + provenance;
  re-file → assert per-fact-type supersede; demographics never written.
