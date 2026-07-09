---
id: 09b
title: Boundary controller — verify scoped token before reading (cross-pid 403)
status: ready-for-merge
depends_on: [09a, 08]
branch: ticket/09b-boundary-controller
base_branch: ticket/09a-patient-summary-service
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml --filter PatientSummaryEndpointTest"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
The read boundary: verify the scoped JWT (T08) BEFORE any data access, then return the
minimum-necessary summary (T09a). A token scoped to patient A used to request patient B
is rejected — and critically, no chart data is read on a denied request.

## Acceptance criteria
- [ ] `PatientSummaryProviderInterface` (`OpenEMR\Modules\AiAgent\Service`) — `getSummary(int $pid): array`.
- [ ] `PatientSummaryService` implements it (add `implements`, no behavior change).
- [ ] `PatientSummaryEndpoint` (`OpenEMR\Modules\AiAgent\Boundary`): constructor
      `(ScopedTokenService $tokens, PatientSummaryProviderInterface $summaries)`;
      `handle(string $token, int $requestedPid): array` calls
      `$tokens->verify($token, $requestedPid)` (throws `InvalidScopedTokenException` on
      bad/expired/wrong-audience/wrong-pid), and ONLY on success returns
      `$summaries->getSummary($requestedPid)`.
- [ ] SECURITY: on any verify failure the summary provider is NOT called (no data read).

## Test plan (orchestrator authors these — LOCKED)
- isolated PHPUnit (`tests/Tests/Isolated/Modules/AiAgent/Boundary/PatientSummaryEndpointTest.php`),
  real `ScopedTokenService` (test key + fake clock) + a fake provider recording calls:
  valid token → returns summary (provider called with the pid); cross-pid token → throws +
  provider NOT called; invalid/garbage token → throws + not called; expired token → throws + not called.

## Notes
The HTTP status mapping (InvalidScopedTokenException → 403) and the actual route live in
T09c/the endpoint wiring; T09b is the unit-locked verify-before-read core. Production
wires a `ERRMODE_EXCEPTION` PDO into PatientSummaryService (per T09a review).
