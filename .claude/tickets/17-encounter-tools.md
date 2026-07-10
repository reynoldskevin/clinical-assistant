---
id: 017
title: Tools — list_encounters + get_encounter (+ UC-4 eval case)
status: ready-for-merge    # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [009, 012]
branch: ticket/17-encounter-tools
base_branch: main          # M1 fully merged to main (ce7eff4); T17 branches off main
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Outcome (ready-for-merge)

- Tests authored + locked: `b9eeac2`. Implementation: `f86e037`. Attempts: 1 (implementer
  passed first try; reviewer APPROVED, no blocking findings).
- Isolated PHP module suite **53/53**, full sidecar suite **47/47** (both verified by the
  orchestrator, not the implementer's claim).
- Regression: full isolated suite green apart from `RestControllers/…/BearerTokenAuthorizationStrategyTest`,
  confirmed **pre-existing on clean main `ce7eff4`** (same 1 failure, 0 AiAgent references,
  passes in isolation) — not a T17 regression.
- Branch `ticket/17-encounter-tools` off `main`. NOT merged (human merges the chain).

## Description

Add the first two M2 chart-navigation tools to the agent: `list_encounters`
(browse the patient's encounter history) and `get_encounter` (fetch one
encounter's detail by id). This is the ticket where the read boundary stops
being single-purpose (`get_patient_summary` only) and becomes a **multi-tool
boundary** — so it also lands the boundary-shape decision that T18–T20 stack on.

## Boundary decision (folded in — the architectural spec T18–T20 reuse)

**One operation-dispatched read boundary. No per-tool auth boilerplate, no new
PHP entry file per tool.**

- **`ChartOperation` backed enum** (`summary` | `list_encounters` |
  `get_encounter`) — the closed set of read operations. The HTTP layer *parses*
  the raw `op` string into the enum (parse, don't validate); an unrecognized
  string is rejected `400` before any token work.
- **`ChartReadEndpoint`** — the single verify-before-read boundary. It verifies
  the scoped JWT **once** for the requested pid (reusing the existing
  `ScopedTokenService` + `BoundaryAuditLoggerInterface` — those ARE the shared
  machinery; do not reimplement them), audits granted/denied, then dispatches to
  the provider via an **exhaustive `match` on `ChartOperation` (no `default`)**.
  Any verification failure (cross-pid / expired / garbage) → throws
  `InvalidScopedTokenException`, and NO provider method is called (fail closed),
  exactly as `PatientSummaryEndpoint` does today.
- **`ChartReadProviderInterface extends PatientSummaryProviderInterface`** — adds
  `listEncounters(int $pid): array` and `getEncounter(int $pid, int $encounterId): array`.
  `PatientSummaryService` implements it. Adding a future tool (T18–T20) = one new
  enum case + one new provider method + one match arm. Nothing else.
- **pid-scoping is the security boundary for model-supplied ids.** `get_encounter`
  takes an `encounter_id` chosen by the model, but the query is
  `WHERE pid = ? AND encounter = ?` — a model cannot read another patient's
  encounter by guessing an id (cross-patient id → empty result, i.e. "not found",
  never another chart's data). The pid remains fixed from the token, never from
  the model.
- **HTTP:** new `public/read.php` accepts `POST {op, pid, params}` + `Authorization: Bearer <jwt>`
  and drives `ChartReadEndpoint` for ALL operations (summary included). The
  existing `public/summary.php` stays as-is (legacy: the currently-deployed
  sidecar still posts to it) — it is NOT removed in this ticket.
- **Sidecar:** the agent gains an **injectable tool registry** (`extra_tools`),
  each entry `{name, description, input_schema, handler(pid, tool_input) -> dict}`.
  The built-in `get_patient_summary` tool is UNCHANGED (T12's locked tests stay
  green — `ClaudeAgent(creator, boundary)` with a bare `boundary(pid)` callable
  keeps working with no `extra_tools`). The production factory builds
  `list_encounters` + `get_encounter` ToolSpecs whose handlers POST to `read.php`
  with the right `op`. A generalized `build_chart_boundary(base_url, jwt)` exposes
  `.summary(pid)` / `.list_encounters(pid)` / `.get_encounter(pid, id)`.

## Acceptance criteria

- [ ] `ChartOperation` backed enum exists with exactly `summary`, `list_encounters`, `get_encounter`.
- [ ] `ChartReadProviderInterface` extends the summary provider with `listEncounters` + `getEncounter`; `PatientSummaryService` implements it.
- [ ] `PatientSummaryService::listEncounters($pid)` returns that patient's encounters (id, encounter, date, reason, provider_id), most-recent-first, and ONLY that patient's.
- [ ] `PatientSummaryService::getEncounter($pid, $encounterId)` returns the one encounter's detail when it belongs to `$pid`; returns `[]` when the id belongs to a DIFFERENT patient (cross-pid isolation) or does not exist.
- [ ] `ChartReadEndpoint::handle($token, $pid, ChartOperation, $params)` verifies before read, audits, and dispatches via exhaustive match; a denied token reads NO data for every operation.
- [ ] Unknown operation string is rejected without touching the provider (parse → 400 at the HTTP layer; enum construction throws on a bad string).
- [ ] Sidecar: `ClaudeAgent` exposes injected `extra_tools`; a `list_encounters` / `get_encounter` tool_use dispatches to the right handler with the session pid (fixed) + model `tool_input`; unknown tool still returns a tool error; the built-in summary path is unchanged.
- [ ] Sidecar factory builds the two ToolSpecs + a chart boundary that POSTs the correct `op` to `read.php`, forwarding the Bearer JWT.
- [ ] UC-4 eval case (`sidecar/evals/uc4.yaml`) exists and loads/validates via the eval harness, exercising an encounter-history question.
- [ ] All prior locked tests (T09*, T12, T13–T16) still pass (regression).

## Test plan (orchestrator authors these — LOCKED)

- **PHP unit (isolated, DB-backed)** — `ChartReadServiceEncountersTest`: seed 2 patients,
  assert `listEncounters` scoping + ordering + fields; assert `getEncounter` returns
  own-pid detail and `[]` for a cross-pid id and for a missing id.
- **PHP unit (isolated, fakes)** — `ChartReadEndpointTest`: valid token dispatches each
  op to a fake provider; cross-pid/expired/garbage token → `InvalidScopedTokenException`
  and provider never called, for `list_encounters` and `get_encounter`; exhaustive-match
  covers all ops. Plus `ChartOperationTest`: valid strings parse, bad string throws.
- **Sidecar unit** — `test_encounter_tools.py`: agent with injected `extra_tools`
  dispatches `list_encounters` / `get_encounter` to the right handler with fixed pid +
  passed input; unknown tool → tool error; summary path unaffected. Factory test:
  the two ToolSpecs are well-formed and the boundary POSTs the right `op` (fake opener).
- **Eval** — `test_uc4_evals.py`: `uc4.yaml` loads and validates through the harness
  like `uc1.yaml` (structure/graders), no live API call.
