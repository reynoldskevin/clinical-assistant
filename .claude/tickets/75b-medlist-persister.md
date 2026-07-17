---
id: 075b
title: med_list persistence — MedicationFactPersister into the Medications panel
status: ready-for-merge
depends_on: []
branch: ticket/75b-medlist-persister
base_branch: main
test_command: "docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter \"MedicationFactPersisterTest|PersistFactsEndpointTest\"'"
full_suite_command: "docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter AiAgent'"
attempts: 1
---

## Description
Persist a `med_list` extraction's derived medication facts into the chart **under the Medications panel**, mirroring how the intake persister already files `current_medications`. The patient-dashboard Medications card reads `lists WHERE type='medication' AND enddate IS NULL` (stats.php `getListData`), so a new `MedicationFactPersister` splits the fact's `medications` string (via `NarrativeFieldSplitter`, skipping negations) and files each as a `lists` row `type='medication'`, provenance-tracked in `ai_derived_fact` and idempotently superseded on re-file by DELETING the prior run's agent-created rows (the panel filters on `enddate`/`activity`, so soft-flag would leave duplicates) — exactly the IntakeFactPersister medication pattern. Route `med_list` through `PersistFactsEndpoint` to the new persister, and allow `med_list` in `persist.php` (dispatch) and `upload.php` (validation; the document store + category are already doc-type-agnostic, defaulting to "Patient Information").

## Acceptance criteria
- [ ] `src/Persistence/MedicationFactPersister.php` — `persist(int $pid, int $documentId, string $extractionRunId, int $createdBy, array $fact, ?string $createdByName = null): array` splits `$fact['medications']` with `NarrativeFieldSplitter` (skips "none"/negations), files each entry as a `lists` row with `type='medication'`, `activity=1`, `title`=the medication text, `pid`, `begdate`=today; records each in `ai_derived_fact` (`fact_type='medication'`, `target_table='lists'`, `active=1`) via `DerivedFactProvenanceService`; returns `['filed' => <int>, 'superseded' => <int>]`.
- [ ] Re-filing the same (pid, document) supersedes the prior run: prior agent-created `lists` medication rows are DELETED (only rows tracked in our own provenance), only the new run's rows remain in the Medications panel, and provenance preserves history (`active=1` for the new rows, `active=0` for the prior).
- [ ] `PersistFactsEndpoint` accepts a `MedicationFactPersister` and `handle(..., 'med_list', $fact, ...)` dispatches to it, returning a normalized response with `doc_type='med_list'` and a `filed` breakdown (`fact_type='medication'`); an unknown doc_type still writes nothing and throws.
- [ ] `public/persist.php` allows `med_list` (validation array) and injects the `MedicationFactPersister`; `public/upload.php` allows `med_list` (validation array) — the source document stores unchanged (doc-type-agnostic; category falls to "Patient Information").
- [ ] No change to `lab_pdf`/`intake_form` persistence behaviour; the existing persister/endpoint tests stay green.

## Test plan (orchestrator authors these)
- `tests/Tests/Isolated/Modules/AiAgent/Persistence/MedicationFactPersisterTest.php` (new) — DB-backed throwaway-schema test mirroring `IntakeFactPersisterTest`: files a `; `-separated `medications` string as N `lists type='medication'` rows (each provenance-tracked); skips negations; a re-file DELETES prior rows and leaves only the new run (no ghost duplicate) with provenance history preserved.
- Extend `tests/Tests/Isolated/Modules/AiAgent/Boundary/PersistFactsEndpointTest.php` — a `testDispatchesMedListToMedicationPersister` asserting `handle(..., 'med_list', ...)` files medications to `lists` and returns `doc_type='med_list'`.
