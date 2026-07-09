---
id: 16
title: UI chat widget + token handoff + render (first in-app)
status: ready-for-merge
depends_on: [12, 08]
branch: ticket/16-ui-widget
base_branch: main
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml --filter 'AgentCardTest|TokenMinterTest'"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
The first in-app agent experience: an AI Clinical Co-Pilot card on the patient summary
that mints a short-lived pid-scoped token and lets the clinician query the chart via the
sidecar. Tested core: `TokenMinter` (composes the T08 auth pieces → a JWT) and `AgentCard`
(the widget HTML, XSS-safe). The runtime glue (subscriber injection, the token HTTP
endpoint, the JS widget) is delivered but activated separately (enable module + browser).

## Acceptance criteria
- [ ] `TokenMinter` (`OpenEMR\Modules\AiAgent\Auth`): static `mint(int $clinicianId,
      string $clinicianUsername, int $pid, string $signingKey, ClockInterface $clock): string`
      — wraps the key in `SigningKey` (rejects weak keys), builds a `ClinicalPrincipal` +
      `PatientId`, and returns a `ScopedTokenService` JWT scoped to the pid.
- [ ] `AgentCard` (`OpenEMR\Modules\AiAgent\Ui`): static `render(int $pid): string` — a
      widget container carrying `data-pid="<int>"` (int-cast, XSS-safe), a heading, and an input.
- [ ] Glue (delivered, not unit-locked): `PatientSummarySubscriber` injects the card;
      `public/token.php` (session + CSRF → TokenMinter); `public/agent-widget.js` (fetch token → call sidecar → render).
- [ ] New PHP files: declare(strict_types=1), docblock header, native types.

## Test plan (orchestrator authors these — LOCKED)
- isolated PHPUnit: `TokenMinterTest` (mint → verify round-trips for the pid; weak key throws;
  wrong-pid verify rejected) and `AgentCardTest` (render carries data-pid + container + heading; int-cast).

## Notes
Activation = enable `oe-module-ai-agent` in OpenEMR + point the widget at the sidecar URL,
then a browser check. The token endpoint's session/CSRF path is runtime glue (its crypto
core, TokenMinter, is the unit-locked part).
