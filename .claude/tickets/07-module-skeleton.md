---
id: 07
title: Module skeleton (oe-module-ai-agent, event-registered)
status: ready-for-merge
depends_on: []
branch: ticket/07-module-skeleton
base_branch: main
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml --filter ModuleBootstrapTest"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
Create the OpenEMR custom module `oe-module-ai-agent` skeleton that loads and
registers an event subscriber on the patient-summary card render event
(`RenderEvent::EVENT_HANDLE`), the hook the AI-agent trigger card will use (T16).
This is the foundation the OAuth/token/boundary tickets (T06/T08/T09) build on.

## Acceptance criteria
- [ ] `interface/modules/custom_modules/oe-module-ai-agent/composer.json` — type
      `openemr-module`, PSR-4 `OpenEMR\Modules\AiAgent\` → `src/`.
- [ ] `openemr.bootstrap.php` entry file registers the namespace and calls
      `Bootstrap::subscribeToEvents()`.
- [ ] `src/Bootstrap.php` — constructor takes an `EventDispatcherInterface`;
      `subscribeToEvents()` registers the subscriber.
- [ ] `src/EventSubscriber/PatientSummarySubscriber.php` — implements
      `EventSubscriberInterface`; `getSubscribedEvents()` maps
      `RenderEvent::EVENT_HANDLE` to a handler method that exists (placeholder body;
      the actual card is T16).
- [ ] All new PHP files: `declare(strict_types=1)`, native types, OpenEMR docblock.

## Test plan (orchestrator authors these — LOCKED)
- isolated PHPUnit (`tests/Tests/Isolated/Modules/AiAgent/ModuleBootstrapTest.php`):
  subscriber subscribes to the card render event; `Bootstrap::subscribeToEvents()`
  registers a listener on a real `EventDispatcher` (`hasListeners`); composer.json is
  a valid openemr-module with the right PSR-4 namespace.

## Notes
Runs in the container (dev deps / PHPUnit installed there). `openemr.bootstrap.php`
is runtime glue (references OEGlobalsBag/ModulesClassLoader), so it is a deliverable
but not unit-tested in isolation; the testable seam is the Bootstrap/Subscriber classes.
