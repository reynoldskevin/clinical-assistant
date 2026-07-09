---
id: 06
title: Agent principal — typed read-only ClinicalPrincipal / PatientId
status: tests-authored
depends_on: [07]
branch: ticket/06-agent-principal
base_branch: ticket/07-module-skeleton
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml --filter ClinicalPrincipalTest"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
Under the custom-JWT auth model (ARCHITECTURE §1a), type the authorization principal
instead of passing bare ints/strings. Two immutable value objects in the module:
`PatientId` (domain primitive) and `ClinicalPrincipal` (the initiating clinician +
pid scope + purpose) — consumed by T08 (JWT claims) and the T09 boundary (authz + audit).

## Acceptance criteria
- [ ] `PatientId` (`OpenEMR\Modules\AiAgent\Auth\PatientId`): `final readonly`, public
      `int $value`; throws `\DomainException` when value <= 0.
- [ ] `ClinicalPrincipal` (`OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal`):
      `final readonly`; holds `int $clinicianId`, `string $clinicianUsername`,
      `PatientId $patientId`, `string $purpose` (default `'treatment'`).
- [ ] Validation: `\DomainException` on clinicianId <= 0 or empty username.
- [ ] Immutable (readonly class) — no setters.
- [ ] `declare(strict_types=1)`, native types, OpenEMR docblock header.

## Test plan (orchestrator authors these — LOCKED)
- isolated PHPUnit (`tests/Tests/Isolated/Modules/AiAgent/Auth/ClinicalPrincipalTest.php`):
  PatientId positivity validation; ClinicalPrincipal accessors, default purpose,
  invalid-clinician/empty-username rejection, readonly-class immutability.

## Notes
Pure value objects — fast isolated tests, no DB. Realizes the CLAUDE.md
"type the principal" / "parse, don't validate" guidance for the authz boundary.
