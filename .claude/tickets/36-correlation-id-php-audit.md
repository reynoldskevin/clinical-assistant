---
id: 36
title: Correlation ID in the PHP boundary audit log (end-to-end trace)
status: todo
depends_on: [35]
branch: ticket/36-correlation-id-php-audit
base_branch: main
test_command: "phpunit-isolated --filter BoundaryAuditCorrelation"
full_suite_command: "phpunit-isolated"
attempts: 0
---

## Description
Second half of the correlation-ID deliverable. T35 forwards an `X-Correlation-ID`
header on every boundary tool call. For a full trace reconstructable from logs
alone, the OpenEMR boundary audit log must record that id, so the sidecar trace
joins to the OpenEMR `log` rows.

Design (minimal ripple — do NOT change `BoundaryAuditLoggerInterface` or the
endpoints, which would break the locked T10 spies): give
`DatabaseBoundaryAuditLogger` an optional per-request `correlationId` via its
constructor and include it in the `comments` column of every row it writes.
`summary.php` / `read.php` read the `X-Correlation-ID` request header and pass it
when constructing the logger.

## Acceptance criteria
- [ ] `DatabaseBoundaryAuditLogger` accepts an optional
      `?string $correlationId = null` constructor arg; when set, every row it
      writes (granted + denied) includes the id in `comments` (e.g. `... cid=<id>`);
      when null, no `cid=` is added (backward compatible — T10 tests stay green).
- [ ] `summary.php` and `read.php` read the `X-Correlation-ID` header (case-
      insensitively, with the same `getallheaders`/`$_SERVER` fallback used for
      Authorization) and pass it into the logger constructor. (Wiring —
      reviewer-verified, per the thin-endpoint pattern.)
- [ ] `BoundaryAuditLoggerInterface`, `PatientSummaryEndpoint`, and
      `ChartReadEndpoint` signatures are UNCHANGED; existing audit tests pass.

## Test plan (orchestrator authors these)
- isolated (DB-backed, throwaway schema like the T10 logger test):
  `tests/Tests/Isolated/Modules/AiAgent/Audit/BoundaryAuditCorrelationTest.php`
  - recordGranted with a constructed correlationId -> comments contains the id
  - recordDenied with a correlationId -> comments contains the id
  - no correlationId (null) -> comments contains no `cid=`
