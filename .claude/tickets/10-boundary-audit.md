---
id: 10
title: Boundary audit logging — every read/denial recorded
status: ready-for-merge
depends_on: [09]
branch: ticket/10-boundary-audit
base_branch: main
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent/Audit"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
The accountability half of the custom-JWT model: every boundary access is audited —
a granted read records the clinician + pid + purpose; a denied attempt records the
requested pid + reason. Denials are audited too (a cross-pid attempt is a security event).

## Acceptance criteria
- [ ] `BoundaryAuditLoggerInterface` (`OpenEMR\Modules\AiAgent\Audit`):
      `recordGranted(ClinicalPrincipal $principal): void`, `recordDenied(int $requestedPid, string $reason): void`.
- [ ] `NullBoundaryAuditLogger` — no-op default.
- [ ] `PatientSummaryEndpoint` gains a `?BoundaryAuditLoggerInterface $audit = null` param
      (defaults to NullBoundaryAuditLogger); on success it calls `recordGranted($principal)`,
      on a verify failure it calls `recordDenied($requestedPid, ...)` then rethrows.
      Verify-before-read is preserved: the provider is still never called on denial, and the
      existing T09b test (2-arg construction) still passes.
- [ ] `DatabaseBoundaryAuditLogger` (injected `\PDO` + `ClockInterface`) writes a `log` row:
      granted → patient_id=pid, user=clinician, success=1, comments=purpose; denied →
      patient_id=requestedPid, success=0, comments=reason.

## Test plan (orchestrator authors these — LOCKED)
- isolated (`Audit/PatientSummaryEndpointAuditTest.php`, spy logger): granted read is audited
  (principal captured), denied access is audited (pid+reason) AND no data read / no grant logged.
- DB-backed (`Audit/DatabaseBoundaryAuditLoggerTest.php`, throwaway `log`): granted/denied each
  write the expected `log` row.

## Notes
Null-object default keeps the endpoint usable without a logger and preserves T09b. Production
wires DatabaseBoundaryAuditLogger with the OpenEMR connection. Later: retention/tamper-evidence (M4).
