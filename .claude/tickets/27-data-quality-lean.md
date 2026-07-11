---
id: 027
title: Data-quality handling (lean close) — free-text-only flag; gap/absence already satisfied; duplicates deferred
status: tests-authored     # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [009]
branch: ticket/27-data-quality-lean
base_branch: main          # T26 merged; branch off main
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests/test_data_quality_evals.py sidecar/tests/test_eval_sweep.py"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Close the M3 data-quality item (USER.md §6) leanly and honestly, rather than
building the full spec. Assessment of the four §6 caveats against what already
exists:

- **Missing fields / `empty ≠ absent` → "not documented":** ALREADY SATISFIED by
  the verification gate (`openemr:_absence` is a first-class valid citation; V2
  demotes ungrounded claims) and locked by `test_verification.py`,
  `uc1_missing_data_no_fabrication`, and the UC-2 absence case. No new work.
- **Stale "active" flags:** ALREADY handled (T19 `get_medications` stale-active
  hedge + `uc6` eval). No new work.
- **Uncoded / free-text-only problems & meds:** the ONE genuinely-new, cheap
  signal. The summary payload already carries the coding field per section —
  `problems.diagnosis` and `medications.rxnorm_drugcode` are empty when the entry
  is documented only as free text — so the agent can flag it WITHOUT any boundary
  change. Add a system-prompt clause + one eval case.
- **Duplicate patient records → DEFERRED (documented).** Real duplicate detection
  needs a cross-patient query, which would breach the pid-scoped, read-only,
  minimum-necessary boundary that is the system's core safety property; demo data
  has no true duplicates (unique synthetic identities); and exact name+DOB matching
  is a toy version of probabilistic record-linkage. Per USER.md §3's own principle
  ("the agent surfaces context and points at deterministic tools, it is not the
  source of truth"), duplicate/merge detection belongs to a deterministic MPI, which
  the agent points at rather than performs. The agent is instructed to say so and
  NOT attempt duplicate detection.

## Design (sidecar-only; no boundary/DB/container change)

- **`agent.py` `_SYSTEM_PROMPT` — data-quality clause.** Append guidance that:
  1. an empty chart section means the data is *not documented* — say "not
     documented"; never infer a clinical negative from absence (`empty ≠ absent`);
  2. when a problem has no `diagnosis` code or a medication has no
     `rxnorm_drugcode`, note it is documented as *free text only* (uncoded), so the
     physician knows it is not coded;
  3. do NOT attempt to identify duplicate patient records — that is a deterministic
     master-patient-index function; if asked, say the agent surfaces context but
     defers duplicate/merge detection to that tool.
- **`evals/uc_data_quality.yaml` (NEW)** — one case
  (`dq_free_text_only_flagged`, `category: data_quality`): asks whether a specific
  problem/med is coded or free-text-only; a grounded answer reads the chart
  (`tool_used`) and flags the free-text/uncoded status (`contains_any`).
- **Docs:** this ticket records the satisfied/deferred mapping; no separate doc file.

## Acceptance criteria
- [ ] System prompt instructs: `empty ≠ absent` → "not documented"; flag free-text-only (uncoded) problems/meds; do NOT perform duplicate detection (defer to MPI).
- [ ] `dq_free_text_only_flagged` case: an answer that reads the chart AND flags the free-text/uncoded status passes; an answer that does not flag it (or does not use the tool) fails.
- [ ] The new case is tagged `category: data_quality`, so the T26 coverage-completeness sweep still passes.
- [ ] No boundary / PHP / container change; gap/absence and stale-active honesty remain covered by existing gate + evals (referenced, not duplicated).
- [ ] Duplicate detection is explicitly documented as deferred (MPI concern), with rationale.
- [ ] All prior sidecar tests still pass (incl. the T26 sweep + completeness).

## Test plan (LOCKED — orchestrator authors)
- `test_data_quality_evals.py`: load `uc_data_quality.yaml`; a tailored injected runner that flags free-text status + used the tool passes; one that omits the flag, and one that skips the tool, fail. Expected substrings read from the loaded case.
- Regression: `test_eval_sweep.py` (T26) still green — the new `data_quality` case keeps the completeness union satisfied.
