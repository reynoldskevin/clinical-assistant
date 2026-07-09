---
id: 01
title: Synthea cohort generation (Python, via Docker)
status: tests-authored
depends_on: []
branch: ticket/01-synthea-gen
base_branch: main
test_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl/tests -q"
full_suite_command: "etl/.venv/bin/pytest -c etl/pytest.ini etl -q"
attempts: 0
---

## Description
A Python wrapper (`etl/synthea_gen.py`) that generates a synthetic patient cohort
by running Synthea inside a pinned Docker Java image (no host Java) and returns the
paths of the generated FHIR patient bundles. Foundation for the T02 patient ETL.

## Acceptance criteria
- [ ] `build_synthea_command(count, output_dir, seed=None)` returns a `docker run`
      argv that bind-mounts `output_dir`, references a Synthea image, passes the
      patient `count`, and enables FHIR export; includes the seed only when given.
- [ ] `generate_cohort(count, output_dir, runner=subprocess.run)` runs the command
      and returns the generated **patient** FHIR bundle paths, EXCLUDING Synthea's
      `hospitalInformation*`/`practitionerInformation*` roster files.
- [ ] Raises `SyntheaError` on a non-zero exit.
- [ ] Raises `SyntheaError` when the run "succeeds" but produces no patient bundles.

## Test plan (orchestrator authors these — LOCKED)
- unit (`etl/tests/test_synthea_gen.py`, mocked runner):
  command construction (docker run / mount / count / fhir export / seed);
  output discovery excludes roster files; error on non-zero exit; error on no bundles.
- integration (opt-in, `-m integration`, deferred): real `docker run` of Synthea
  for a tiny cohort produces ≥1 patient bundle. Not in the default test_command.

## Notes
Real generation is run at T02 load time (needs the Docker image pull). Unit tests
mock the runner so the TDD loop is fast + deterministic.
