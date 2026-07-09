---
id: 08
title: Scoped-token mint/verify service (5-min pid-JWT, clock-injected)
status: tests-authored
depends_on: [06]
branch: ticket/08-scoped-token
base_branch: ticket/06-agent-principal
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml --filter ScopedTokenServiceTest"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
The security core of the custom-JWT auth model (ARCHITECTURE §1a): mint a short-lived,
pid-scoped JWT from a `ClinicalPrincipal` and verify it at the boundary. Uses the vetted
`firebase/php-jwt` (HS256) with an injected PSR-20 `ClockInterface` so expiry is
deterministic and testable — never hand-rolled crypto.

## Acceptance criteria
- [ ] `InvalidScopedTokenException` (`OpenEMR\Modules\AiAgent\Auth`) extends `\RuntimeException`.
- [ ] `ScopedTokenService` (`OpenEMR\Modules\AiAgent\Auth`): constructor
      `(string $signingKey, Psr\Clock\ClockInterface $clock, string $audience = 'oe-ai-agent-boundary', int $ttlSeconds = 300)`.
- [ ] `mint(ClinicalPrincipal $principal): string` — HS256 JWT with claims for
      clinician id/username, pid, purpose, audience, iat = clock now, exp = now + ttl.
- [ ] `verify(string $token, int $requestedPid): ClinicalPrincipal` — validates signature,
      expiry (against the injected clock), audience, and that the token's pid == requestedPid;
      returns the reconstructed `ClinicalPrincipal`. Throws `InvalidScopedTokenException`
      on ANY failure (bad signature, expired, wrong audience, pid mismatch).
- [ ] The service drives firebase's time check from the injected clock (set
      `\Firebase\JWT\JWT::$timestamp`) so expiry is deterministic.

## Test plan (orchestrator authors these — LOCKED)
- isolated PHPUnit (`tests/Tests/Isolated/Modules/AiAgent/Auth/ScopedTokenServiceTest.php`),
  fake ClockInterface: mint→verify round-trip; expired (advance clock past ttl); tampered
  token; wrong requestedPid; token signed with a different key.

## Notes
The HTTP token endpoint (`POST .../token`: active session + CSRF → mint) is runtime glue
requiring an OpenEMR session, so it is DEFERRED to T09 (the boundary), where it is
integration-tested. T08 delivers the unit-locked crypto core only.
