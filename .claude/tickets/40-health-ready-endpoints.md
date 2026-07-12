---
id: 40
title: Separate /health (liveness) and /ready (dependency-checking) endpoints
status: ready-for-merge
depends_on: []
branch: ticket/40-health-ready-endpoints
base_branch: main
test_command: "python -m pytest sidecar/tests/test_health_ready.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
Deliverable: separate `/health` (is the process alive) and `/ready` (are
dependencies reachable). `/ready` must actually check OpenEMR, the LLM provider,
and the observability backend are reachable — not return 200 unconditionally.
Also add both to the Postman collection + README.

## Acceptance criteria
- [ ] `sidecar/health.py`:
  - `liveness()` returns a small dict (process is alive) — always healthy.
  - `http_reachable(url, opener, headers, timeout)` returns `(True, detail)` when
    the server responds (INCLUDING a 4xx/5xx HTTPError — the server answered),
    `(False, "unreachable")` on connection error/timeout.
  - `build_readiness_checks(summary_url, anthropic_key, braintrust_key, opener)`
    returns named checks `openemr` (the boundary summary_url), `llm` (Anthropic
    API), `observability` (Braintrust API when a key is set, else a
    `(None, "not_configured")` skip).
  - `evaluate_readiness(checks)` runs them and returns `(status, body)` where
    body is `{"ready": bool, "checks": {name: {ok, detail}}}`; status is 200 when
    ready else 503. A check returning `ok is False` fails readiness; `ok is None`
    (not_configured) does not.
  - `ready_response(summary_url, anthropic_key, braintrust_key, opener)` = build +
    evaluate (the convenience the server calls).
- [ ] `server.py` `do_GET`: `/health` -> 200 liveness (unconditional);
      `/ready` -> `ready_response(...)` with the real config + urllib opener
      (200 or 503); other GET paths -> 404. (Wiring — reviewer-verified.)
- [ ] Postman collection gains "Health" (GET `{{sidecar_base_url}}/health`) and
      "Readiness" (GET `{{sidecar_base_url}}/ready`) requests, documented.
- [ ] `postman/README.md` documents the two endpoints.
- [ ] No behaviour regression (full sidecar suite green).

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_health_ready.py`
  - liveness ok
  - http_reachable: responds -> True; HTTPError -> True (reachable); conn error -> False
  - build_readiness_checks: names present; braintrust unset -> observability skip
  - ready_response: all reachable -> 200 ready; openemr down -> 503 not ready;
    braintrust configured+down -> 503; braintrust unset -> 200 (not_configured)
