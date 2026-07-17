---
id: 53a
title: Derived-fact provenance table + DerivedFactProvenanceService (supersede-by-run)
status: ready-for-merge
depends_on: []
branch: ticket/53a-derived-fact-provenance
base_branch: main
test_command: "docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter DerivedFactProvenance'"
full_suite_command: "docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit --testsuite services --testdox' ; npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 0
---

## Description
The foundation for T53 (persist AI-extracted document facts into the chart). Every
record the persist step writes must be traceable to the document + extraction run
it came from, and re-filing a re-extracted document must SUPERSEDE the prior run's
derived records rather than duplicating them. This ticket adds the provenance
store; T53b/T53c write actual clinical records against it; T53d exposes the
clinician-gated endpoint.

Two parts, both in the AI module (OpenEMR-side PHP):

1. **Schema — `ai_derived_fact` table** via a Doctrine migration
   (`db/Migrations/VersionYYYYMMDDHHMMSS.php`, `CreateTableTrait`). One row per
   clinical record the agent files, columns:
   - `id` BIGINT PK autoincrement
   - `uuid` BINARY(16) (UuidRegistry) — stable external id
   - `pid` INT — patient scope
   - `source_document_id` INT — FK-in-spirit to `documents.id` (the uploaded doc)
   - `extraction_run_id` VARCHAR(64) — the sidecar extraction correlation id
   - `doc_type` VARCHAR(31) — `lab_pdf` | `intake_form`
   - `fact_type` VARCHAR(31) — `lab_result` | `medication` | `allergy` |
     `condition` | `family_history` | `chief_concern`
   - `target_table` VARCHAR(64) — where the clinical record lives
     (`procedure_result`, `prescriptions`, `lists`, …)
   - `target_id` BIGINT — the created record's numeric id
   - `target_uuid` BINARY(16) NULL — the created record's uuid, if any
   - `fact_summary` VARCHAR(255) — human label for card/audit display
   - `created_by` INT — clinician users.id who filed it
   - `created_at` DATETIME
   - `superseded_at` DATETIME NULL
   - `active` TINYINT NOT NULL DEFAULT 1
   - indexes: `(pid, source_document_id, fact_type)`, `(extraction_run_id)`
   Because the Doctrine migration system is not auto-run in this fork (see
   `db/README.md`), the migration is applied by hand: `./cli migrate` in the dev
   container (ENVIRONMENT set) locally, and hand-applied on Railway (schema-drift
   memory). Record the change in `W2_MIGRATIONS.md`.

2. **`DerivedFactProvenanceService`** (`src/Persistence/DerivedFactProvenanceService.php`,
   `OpenEMR\Modules\AiAgent\Persistence`). Constructor takes a DB executor
   (inject `QueryUtils`-style callables so the record/supersede SQL can be unit
   tested without a live table). Methods:
   - `record(DerivedFactRef $ref): int` — insert one provenance row (mints the
     uuid), returns the new id.
   - `supersedePriorRun(int $pid, int $documentId, string $factType): list<DerivedFactRef>`
     — mark all currently-`active` rows for `(pid, documentId, factType)` as
     superseded (`active=0`, `superseded_at=NOW()`) and RETURN their target refs
     so the caller (T53b/c) can deactivate the underlying clinical records. Idempotent.
   - `activeFor(int $pid, int $documentId): list<DerivedFactRef>` — active rows for
     display/audit.
   `DerivedFactRef` is a readonly DTO (fact_type, target_table, target_id,
   target_uuid, fact_summary, extraction_run_id).

No clinical-record writes happen in this ticket — only the provenance store and
its supersede bookkeeping.

## Acceptance criteria
- [x] A Doctrine migration creates `ai_derived_fact` with the columns + indexes
  above; `down()` drops it. Applying it (`./cli migrate`) in the dev container
  creates the table; a `W2_MIGRATIONS.md` entry documents it.
- [x] `DerivedFactProvenanceService::record()` inserts a row with a fresh uuid and
  the given refs, and returns its id; the row is readable via `activeFor()`.
- [x] `supersedePriorRun(pid, doc, factType)` flips exactly the matching active
  rows to `active=0` with a `superseded_at`, leaves other pids/docs/factTypes
  untouched, returns the superseded refs, and is idempotent (a second call returns
  nothing and changes nothing).
- [x] `activeFor()` returns only `active=1` rows for the pid+document.
- [x] Unit-level: record/supersede SQL is exercised with an injected fake executor
  (no DB) proving the WHERE/SET shapes; DB-backed: the same against the real table.
- [x] No regression in the services suite or the module jest suite.

## Test plan (orchestrator authors these)
- isolated unit (no DB) `tests/Tests/Isolated/...` or module test: inject a fake
  executor capturing SQL+binds; assert record() binds all columns + a uuid, and
  supersedePriorRun() emits the `active=0, superseded_at=NOW` UPDATE scoped to
  `(pid, source_document_id, fact_type)` and returns the prior refs.
- DB-backed (services suite) `tests/Tests/Services/AiAgent/DerivedFactProvenanceServiceTest.php`:
  against the real migrated table — record two runs for one document, assert run 2
  supersedes run 1 (run 1 rows go inactive, run 2 active), activeFor reflects it,
  cross-pid/doc isolation holds. Orchestrator applies the migration to the dev DB
  before running.
