---
id: 39
title: Runnable Postman collection + dev-gated token mint helper
status: ready-for-merge
depends_on: []
branch: ticket/39-postman-collection
base_branch: main
test_command: "phpunit-isolated --filter DevTokenMinter"
full_suite_command: "phpunit-isolated"
attempts: 1
---

## Description
Deliverable: a runnable Postman API collection covering the core agent endpoints,
runnable by graders without reading source. The endpoints (summary.php, read.php,
sidecar /ask + /ask/stream) all need a pid-scoped JWT that token.php only mints
from a browser session (auth + CSRF + patient-in-context). To make the collection
self-contained, add a DEV-GATED mint helper: a token-mint path that is OFF by
default and fails closed, so it never weakens the real auth model, but on the
synthetic demo lets the collection mint a JWT for any pid programmatically.

## Acceptance criteria
- [ ] `DevTokenMinter` (security-critical seam): constructed with an explicit
      `bool $enabled` gate. `mintForPid(pid, clinicianId, username)` throws
      `DevTokenMintDisabledException` when NOT enabled (fail closed); when enabled,
      returns a normal pid-scoped JWT that `ScopedTokenService::verify(token, pid)`
      accepts, and which is cross-pid-rejected (verify for a different pid throws).
- [ ] `Config::devMintEnabled(): bool` reads `dev_token_mint` / `OE_AI_AGENT_DEV_MINT`
      (truthy = enabled), defaulting to false. (Config plumbing — reviewer-verified,
      like signingKey.)
- [ ] `public/dev_mint.php` endpoint: returns 404 when the gate is disabled (does
      not advertise itself); when enabled, mints a JWT for the requested pid via
      DevTokenMinter and returns `{token, pid}`. Never leaks exception detail.
      (Wiring — reviewer-verified.)
- [ ] `postman/oe-ai-agent.postman_collection.json` — a valid Postman v2.1
      collection with collection variables (base URLs, pid, jwt) and requests for:
      dev-mint (captures the JWT into a variable via a test script), get patient
      summary (summary.php), chart read ops (read.php: list_encounters,
      get_medications, search_chart), ask (/ask), ask stream (/ask/stream). Each
      request has a description; the runner can execute the whole flow.
- [ ] `postman/README.md` documents enabling the dev gate (synthetic demo only,
      never real PHI) and running the collection.

## Test plan (orchestrator authors these)
- isolated (pure): `tests/Tests/Isolated/Modules/AiAgent/Auth/DevTokenMinterTest.php`
  - disabled -> mintForPid throws DevTokenMintDisabledException
  - enabled -> token verifies for its pid (clinician/pid correct)
  - enabled -> token is pid-scoped (verify for another pid throws)
