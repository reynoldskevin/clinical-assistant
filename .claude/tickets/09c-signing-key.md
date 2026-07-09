---
id: 09c
title: SigningKey value object — enforce HS256 key strength (>=32 bytes)
status: tests-authored
depends_on: [08]
branch: ticket/09c-token-endpoint
base_branch: ticket/09b-boundary-controller
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml --filter SigningKeyTest"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
Close the key-strength gap the T08 review flagged: a typed `SigningKey` that refuses
a weak HS256 secret (< 32 bytes / 256 bits) at construction. The token-mint HTTP
endpoint that would consume it (session+CSRF → mint) is DEFERRED to the UI/sidecar
wiring (T12/T16), where it can be exercised end-to-end in a browser rather than
shipped as untested session/CSRF/routing glue here.

## Acceptance criteria
- [ ] `SigningKey` (`OpenEMR\Modules\AiAgent\Auth`): `final readonly`, `public string $value`.
- [ ] Throws `\DomainException` when the key is shorter than 32 bytes (incl. empty).
- [ ] Accepts a 32-byte key and longer.
- [ ] `declare(strict_types=1)`, native types, OpenEMR docblock, immutable.

## Test plan (orchestrator authors these — LOCKED)
- isolated PHPUnit (`tests/Tests/Isolated/Modules/AiAgent/Auth/SigningKeyTest.php`):
  accepts 32-byte and longer keys; rejects 31-byte and empty; readonly-final.

## Notes
`ScopedTokenService` (T08) should be constructed with `(new SigningKey($cfg))->value`
by the future endpoint/factory, so a weak configured key fails fast. This completes
the T09 tested boundary core (T09a service + T09b verify + T09c key guard). Remaining
T09 glue (the `POST .../token` route + `get_patient_summary` HTTP route) lands with the
sidecar/UI so it gets an end-to-end/browser test.
