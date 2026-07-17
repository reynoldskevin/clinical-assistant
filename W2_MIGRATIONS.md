# W2 Manual Migrations

The Doctrine migration system is not auto-run in this fork (see `db/README.md`).
Migrations here are applied by hand: `./cli migrate` in the dev container
(`ENVIRONMENT` set), and hand-applied on Railway (persisted DB never runs
`sql_upgrade`; see the schema-drift memory).

## 2026-07-16 — `ai_derived_fact` (T53a)

- Migration: `db/Migrations/Version20260717020718.php`
- Creates the `ai_derived_fact` provenance table: one row per clinical record the
  AI persist step files into the chart, traced to its source document +
  extraction run. Backs `DerivedFactProvenanceService` (record / supersede-by-run
  / activeFor) so a re-extracted document supersedes the prior run's derived
  records (`active=0`, `superseded_at`) instead of duplicating them.
- Columns: `id`, `uuid` BINARY(16), `pid`, `source_document_id`,
  `extraction_run_id`, `doc_type`, `fact_type`, `target_table`, `target_id`,
  `target_uuid` BINARY(16) NULL, `fact_summary`, `created_by`, `created_at`,
  `superseded_at` NULL, `active` DEFAULT 1. Indexes on
  `(pid, source_document_id, fact_type)` and `(extraction_run_id)`.
- Apply: `docker exec -e ENVIRONMENT=development development-easy-openemr-1 sh -c
  'cd /var/www/localhost/htdocs/openemr && php cli migrate --no-interaction'`
  locally; hand-apply the equivalent CREATE TABLE on Railway.
