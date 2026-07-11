---
id: 29
title: V7 — block status/negation contradictions of the record (verification gate)
status: todo
depends_on: []
branch: ticket/29-v7-status-contradiction
base_branch: main
test_command: "python -m pytest sidecar/tests/test_verification_status.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description
The verification gate grounds citations (V1), demotes ungrounded numerics (V2),
blocks misattributed meds by NAME (V3), and blocks identifier leaks (V6). But a
non-numeric contradiction of a record's own STATUS slips through: the agent can
say a med/problem is "resolved" or "discontinued" while the cited record is
marked active. The brief: *"A response that violates what the underlying data
actually says is a failure."* V3 only checks the drug name; V2 only fires on
digits. Close the status-contradiction case.

Records for `prescription:`/`list:` refs carry `active` (bool) and
`status_conflict` (bool — active=1 but has an end_date, the stale-active hedge).

## Acceptance criteria
- [ ] V7 (BLOCKING): a citation to a med/allergy/problem record
      (`prescription:`/`list:`) whose record is `active === true` and NOT
      `status_conflict`, carried in a sentence that asserts an inactive/negated
      status (resolved / discontinued / inactive / no longer / not taking / …),
      raises a `contradicts_status` flag and blocks (safe fallback, verdict
      `blocked`).
- [ ] The ambiguous stale-active case is NOT blocked: when the record has
      `status_conflict === true`, a "resolved"-type assertion is allowed (the
      agent is entitled to hedge — end_date exists).
- [ ] An accurate assertion is NOT blocked: an inactive record
      (`active === false`) described as resolved/discontinued passes.
- [ ] A current/positive-status sentence about an active record is NOT blocked.
- [ ] V7 does not fire for non-med/allergy refs (e.g. `pnote:`).
- [ ] Backward compatible: with `retrieved_data=None`, V7 does not run (T23
      V1/V2 behaviour preserved).
- [ ] Blocking precedence holds: a status contradiction blocks even when other
      (pass_with_flags) conditions are present.

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_verification_status.py`
  - active record + "resolved" citing it -> blocked, `contradicts_status`, fallback
  - status_conflict record + "resolved" -> not blocked
  - inactive record + "discontinued" -> not blocked
  - active record + accurate current-status sentence -> not blocked
  - pnote ref + "resolved" -> not blocked (V7 scope)
  - retrieved_data=None -> not blocked (backward compat)
  - precedence: status contradiction wins over pass_with_flags
