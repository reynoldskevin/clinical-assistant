---
id: 061
title: Finalize W2_ARCHITECTURE.md + PHI-detection CI check + SLO/baseline numbers
status: tests-authored
depends_on: []
branch: ticket/61-phi-check-slo-baselines
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_phi_detection.py tests/test_architecture_doc.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Close out the Week-2 engineering docs and privacy posture. Implement the PHI-detection CI check that `W2_ARCHITECTURE.md` §11 already describes as existing: a `phi_scan` detector plus a log/trace-emission guard that fails the build if patient identifiers (SSN/MRN/DOB/phone) reach the sidecar's emitted log or per-turn trace output, wired as a dedicated blocking `security:phi` job in the GitLab pipeline (mirroring the T66 `security:deps`/`security:scan` jobs). Fill in §7's placeholder SLO targets with the concrete latency baselines from `METRICS_WEEK1.md` so the SLOs are real numbers, not `< target`. Finalize the architecture doc.

## Acceptance criteria
- [ ] `sidecar/phi_scan.py` exposes `find_phi(text)` (detects `ssn`, `mrn`, `dob`, `phone`, `lab_value` shapes) and `find_identifiers(text)` (direct patient identifiers only — `ssn`/`mrn`/`dob`/`phone`, excluding clinical value shapes that legitimately appear in public guideline text).
- [ ] The scanner catches each PHI shape and returns clean on PHI-free outcome-style events (`{"field":"hba1c","outcome":"ok"}`).
- [ ] Log/trace-emission guard: exercising the real Week-2 emission points (the per-turn `agent turn: … trace=…` log line via `process_ask`; the serialized `TraceCollector.summary()`) yields output containing NO direct patient identifiers.
- [ ] `.gitlab-ci.yml` declares a `security:phi` job in the `security` stage that runs the PHI check offline (no secrets), running the `test_phi_detection` guard.
- [ ] `W2_ARCHITECTURE.md` §7 SLOs are concrete: the `< target seconds` placeholder is gone, replaced with concrete p95 latency numbers (with units) drawn from and referencing `METRICS_WEEK1.md`.
- [ ] `W2_ARCHITECTURE.md` retains all 14 sections; §11 still references the PHI-detection CI check.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_phi_detection.py` — scanner unit tests, log/trace emission guard, and the `security:phi` CI-job config contract.
- `sidecar/tests/test_architecture_doc.py` — doc-finalization guard (all sections present, SLO placeholders replaced with concrete numbers referencing METRICS_WEEK1.md, §11 PHI-check reference).
