---
id: 68
title: Proactive wrong-chart / wrong-patient check at extraction time
status: done
depends_on: [47]
branch: ticket/68-extract-identity-check
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_identity_check.py tests/test_extract_identity_wiring.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
New requirement. Today the wrong-chart / wrong-patient safety check is
prompt-based: a system-prompt instruction (feat/wrong-chart-identity-check) tells
the agent to cross-check an uploaded document's identifiers against the chart's
demographics — but ONLY when a question is later asked about that form. The desired
lifecycle is upload → extract → check-file-matches-patient-context → warn: the
"Possible wrong-chart / wrong-patient upload" banner (with the accompanying
"identifiers do not match this chart:" detail) should appear automatically the
moment an intake form is extracted, before any question.

This ticket adds a DETERMINISTIC, offline identity check to the extraction path
(no extra LLM call — zero added latency/cost, fully testable, matching the repo's
pure-gate ethos):

1. **Pure identity-check module (`sidecar/identity_check.py`).**
   `check_identity(intake_demographics: str | None, chart_demographics: dict | None)
   -> IdentityCheck` parses the strong identifiers out of the VLM-normalized intake
   demographics string (DOB as an ISO `YYYY-MM-DD` date; sex as an M/F/male/female
   token; surname/name tokens) and compares them to the chart's structured
   demographics dict (`fname`, `lname`, `dob`, `sex`, …). It is CONSERVATIVE: an
   identifier is only "checked" when it is confidently present in BOTH sides, and a
   mismatch is only raised on a clear conflict of a checked identifier — an absent or
   unparseable identifier is never a mismatch (no false alarms). `IdentityCheck`
   carries `matches: bool`, `mismatched_identifiers: list[str]` (canonical order
   `["name", "DOB", "sex"]`), and `checked_identifiers: list[str]`.
2. **Wire it into the extract path (`server.default_extract_builder`).** For
   `doc_type == "intake_form"`, after the fact is extracted, fetch the chart's own
   demographics through the summary boundary and run `check_identity`. The
   `/extract` response gains an `identity_check` block
   (`{"matches", "mismatched_identifiers", "warning"}`, `warning ==
   "possible_wrong_chart"` iff `matches` is false) whenever the check ran. The check
   is best-effort and fail-open: if the summary boundary is unavailable, or the
   doc is not an intake form, `identity_check` is omitted and the extraction still
   succeeds (a verification outage must not block showing the extracted fact, and we
   never cry wolf on an unverifiable upload).
3. **Render the banner on the card (`agent-widget.js`).** When the extract response
   carries `identity_check.matches === false`, `renderExtraction` shows a prominent
   "Possible wrong-chart / wrong-patient upload" banner and an "identifiers do not
   match this chart: &lt;list&gt;" line above the extracted fields, built with
   createElement/textContent (no HTML injection), matching the existing safe render.

The existing prompt-based check (agent.py) stays as the answer-time backstop; this
adds the proactive extract-time surface the requirement asks for.

## Acceptance criteria
- [x] `check_identity` flags a clear conflict: differing DOB → `"DOB"` in
  `mismatched_identifiers`; differing sex → `"sex"`; a chart surname absent from the
  intake name → `"name"`. `matches` is false iff `mismatched_identifiers` is non-empty.
- [x] It is conservative: an identifier absent or unparseable on either side is NOT
  checked and NEVER a mismatch; when nothing is comparable, `matches` is true with
  empty `checked_identifiers` (fail-open, no warning). `None`/empty inputs are safe.
- [x] Matching is case- and format-insensitive where it should be: `"Female"` vs
  `"F"`, `"male"` vs `"M"` match; a surname matches as a case-insensitive token;
  only ISO `YYYY-MM-DD` DOBs are compared (an unparseable date is not checked).
- [x] Real-fixture behaviour: intake `"Jordan A. Rivera; DOB 1988-03-02; Male"`
  against a chart `{lname: "Cruickshank494", fname: "Brett333", dob: "1925-06-24",
  sex: "Female"}` → mismatch on name+DOB+sex; a matching intake
  (`"Brett333 Cruickshank494; DOB 1925-06-24; Female"`) → `matches` true.
- [x] `default_extract_builder`'s `/extract` response includes an `identity_check`
  block for an `intake_form` whose identifiers mismatch the chart summary
  (`matches` false, the mismatched list, `warning == "possible_wrong_chart"`), and
  a matching intake yields `matches` true.
- [x] The check is scoped + fail-open: a `lab_pdf` extraction carries NO
  `identity_check`; if the summary boundary raises, the extraction still returns the
  fact (200) with no `identity_check` and no error surfaced.
- [x] `agent-widget.js` renders the "Possible wrong-chart / wrong-patient upload" +
  "identifiers do not match this chart:" banner when `identity_check.matches` is
  false (verified by reading; no HTML injection).
- [x] No regression: the existing extractor / extract-endpoint / intake-tool /
  wrong-chart-eval tests and the full sidecar suite stay green; the prompt-based
  agent check is untouched.

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_identity_check.py`: exact match; DOB/sex/name conflict
  each in isolation; partial (sex matches, DOB differs → only DOB); conservative
  no-false-positive (missing DOB, missing name, no chart demographics); case/format
  insensitivity; the two real fixtures; None/empty inputs; determinism; canonical
  mismatched order; `matches == (mismatched == [])`.
- unit `sidecar/tests/test_extract_identity_wiring.py`: `default_extract_builder`
  (+ `process_extract`) with fake chart + summary boundaries — intake mismatch →
  response `identity_check.matches` false with the list + warning; intake match →
  `matches` true; `lab_pdf` → no `identity_check`; summary boundary raising →
  200 with the fact and no `identity_check` (fail-open); the response stays JSON-safe.
