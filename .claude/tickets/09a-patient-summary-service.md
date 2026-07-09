---
id: 09a
title: PatientSummaryService — minimum-necessary chart summary (DB-backed)
status: ready-for-merge
depends_on: [05, 08]
branch: ticket/09a-patient-summary-service
base_branch: main
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml --filter PatientSummaryServiceTest"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent"
attempts: 0
---

## Description
The read core of the T09 boundary: assemble a **minimum-necessary** clinical summary
for one patient from the ETL-populated tables. Connection is injected (`\PDO`) so it is
testable against a disposable throwaway schema (the proven ETL pattern, PHP side).

## Acceptance criteria
`PatientSummaryService(\PDO $db, int $recentLimit = 5)` with `getSummary(int $pid): array`
returning keys:
- [ ] `demographics` — pid, fname, lname, dob (Y-m-d), sex, race, ethnicity from `patient_data`.
- [ ] `problems` — `lists` where type='medical_problem' AND **activity=1** (active only); title, diagnosis, date.
- [ ] `medications` — `prescriptions` where **active=1** (active only); drug, rxnorm_drugcode, date_added.
- [ ] `allergies` — `lists` where type='allergy' AND activity=1; title.
- [ ] `recent_encounters` — `form_encounter` for the pid, **most-recent-first, capped at recentLimit**; date, reason.
- [ ] `recent_vitals` — `form_vitals`, most-recent-first, capped; date, bps, bpd, pulse, weight.
- [ ] `recent_labs` — `procedure_result` joined report→order for the pid, most-recent-first, capped; result_code, result, units, date.
- [ ] Minimum-necessary: inactive problems/meds excluded; recent_* lists bounded by recentLimit.

## Test plan (orchestrator authors these — LOCKED)
- DB-backed PHPUnit (`tests/Tests/Isolated/Modules/AiAgent/Service/PatientSummaryServiceTest.php`):
  self-managed throwaway schema cloned from `openemr`, seeded with one patient + active/inactive
  problems & meds, an allergy, 7 encounters, vitals, and a lab chain. Asserts demographics,
  active-only filtering, and recent-section bounding/ordering.

## Notes
Injected `\PDO` (not `new` inside the class) keeps DI + testability; production wires the
OpenEMR connection. Next: T09b (boundary controller: JWT verify + cross-pid 403 + JSON).
