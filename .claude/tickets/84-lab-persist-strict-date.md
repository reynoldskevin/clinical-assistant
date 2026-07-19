---
id: 84
title: LabFactPersister must file when the collection date is missing (strict SQL)
status: tests-authored
depends_on: []
branch: ticket/84-lab-persist-strict-date
base_branch: main
test_command: "docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && AI_DB_HOST=mysql ./vendor/bin/phpunit --no-coverage tests/Tests/Isolated/Modules/AiAgent/Persistence/LabFactPersisterStrictDateTest.php'"
full_suite_command: "docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && AI_DB_HOST=mysql ./vendor/bin/phpunit --no-coverage tests/Tests/Isolated/Modules/AiAgent/Persistence/'"
attempts: 0
---

## Description
"Accept & file to chart" fails for a lab PDF on the live (Railway) demo: nothing files. Root cause is a SQL-dialect bug that passes local tests and 500s on Railway. The VLM frequently cannot ground a lab's collection date, so `/extract` returns `collection_date: null`; `LabFactPersister` reads it defensively as `''` and binds that empty string straight into the `datetime` columns `procedure_order.date_collected`, `procedure_report.date_collected`, and `procedure_report.date_report`. Railway MySQL runs in strict mode (`STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE`), which REJECTS `''` for a datetime — the INSERT throws, `persist.php` returns an error, and the card shows "file failed". Local MariaDB is not strict, so the same insert silently coerces and the existing DB-backed test (which also uses a valid date) never catches it. Additionally `dateOrDefault` (used for `date_ordered` and `procedure_result.date`) is `collectionDate` verbatim whenever it is non-empty, so a non-empty-but-unparseable date (e.g. "May 2024") would fail strict mode too. Fix: normalize the extracted collection date to a valid SQL datetime or `NULL` before binding — bind `NULL` (not `''`) for the nullable `date_collected`/`date_report` columns when the date is missing or unparseable, and fall back to today's date for the required `date_ordered`/`result.date`. Intake filing is unaffected (it does not touch `procedure_*` datetimes).

## Acceptance criteria
- [ ] AC1 — Under strict SQL mode, filing a LabFact whose `collection_date` is `''` (empty) SUCCEEDS (returns `filed = 1`) instead of throwing; `procedure_order.date_collected`, `procedure_report.date_collected`, and `procedure_report.date_report` are stored as `NULL` (never `''` or a zero-date), and the `procedure_result` row (test_name/value/units/range) is filed intact.
- [ ] AC2 — Under strict SQL mode, filing a LabFact whose `collection_date` is a non-empty but unparseable string (e.g. `"May 2024"`) also SUCCEEDS (never throws); the three datetime columns above are `NULL` and the required `procedure_order.date_ordered` + `procedure_result.date` fall back to a valid date (today).
- [ ] AC3 — No regression: a valid ISO `collection_date` (e.g. `2026-05-01`) is preserved on `date_collected`/`date_report` and `procedure_result.date`, exactly as today (the existing LabFactPersisterTest suite stays green).

## Test plan (orchestrator authors these; LOCKED)
- php isolated, DB-backed (new `tests/Tests/Isolated/Modules/AiAgent/Persistence/LabFactPersisterStrictDateTest.php`): clone the `procedure_*` + `ai_derived_fact` tables into a throwaway DB (mirroring LabFactPersisterTest), then `SET SESSION sql_mode` to Railway's strict set on the persister's connection so the test reproduces production. Assert: (AC1) persisting with `collection_date => ''` returns `filed==1` and the three datetime columns are `NULL` with the result row intact; (AC2) `collection_date => 'May 2024'` also files with those columns `NULL` and `date_ordered`/`result.date` a valid date; (AC3) a valid `2026-05-01` is preserved. The current code throws a `PDOException` under strict mode for AC1/AC2 → red before the fix.
