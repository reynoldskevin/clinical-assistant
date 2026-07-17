---
id: 074
title: Document GET /metrics in the OpenAPI spec + README (+ Postman)
status: done
depends_on: []
branch: ticket/74-metrics-openapi-readme
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_openapi_spec.py tests/test_metrics_openapi.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Document the merged `GET /metrics` endpoint across the sidecar's published API surfaces so it stops being undocumented drift. Add a `/metrics` path to `sidecar/openapi.yaml` (GET, unauthenticated like `/health` and `/ready`, a 200 response schema matching the server's real body — `{panels:{ingestion_count, extraction:{total,ok,field_pass_rate,by_outcome}, retrieval:{hits,misses,hit_rate}, routing}, alerts:{extraction_failure:{firing,rate,failed,total}}, window:{events,buffer_max}}`), add a matching `/metrics` request to the Postman collection, and list `/metrics` in the README alongside the other live endpoints. The T60 locked `test_openapi_spec.py` pins the spec's path set (and Postman coverage) to a fixed endpoint list, so this ticket extends that contract to include `/metrics` and adds a spec⇄server round-trip guard proving the documented response shape equals what the handler actually returns.

## Acceptance criteria
- [ ] `sidecar/openapi.yaml` documents `GET /metrics`: a summary/description, NO `security` requirement (unauthenticated, like `/health`/`/ready`), and a `200` response whose `application/json` schema is an object with top-level properties `panels`, `alerts`, `window`; `panels` documents `ingestion_count` + nested `extraction` (`total`, `ok`, `field_pass_rate`, `by_outcome`), `retrieval` (`hits`, `misses`, `hit_rate`), and `routing`; `alerts` documents `extraction_failure` (`firing`, `rate`, `failed`, `total`); `window` documents `events` and `buffer_max`.
- [ ] The spec's documented `/metrics` 200 response shape MATCHES the real server body: the top-level keys and the nested `panels`/`alerts`/`window` sub-keys the handler returns equal what the spec documents (a live round-trip through the real `make_handler` `/metrics` handler, not an assumed shape).
- [ ] The Postman collection (`postman/oe-ai-agent.postman_collection.json`) gains a `GET {{sidecar_base_url}}/metrics` request so the T60 coverage test (which iterates the endpoint set) passes for `/metrics`.
- [ ] `README.md` documents the `/metrics` endpoint (a live-endpoint link/line alongside the deployed demo / ready / health entries).
- [ ] The existing T60 contract tests still pass (the `EXPECTED_ENDPOINTS` set now includes `/metrics`); no server/behaviour change — this ticket edits only the spec, the Postman collection, the README, and the (orchestrator-authored) tests.

## Test plan (orchestrator authors these)
- Extend `sidecar/tests/test_openapi_spec.py` — add `"/metrics": {"get"}` to `EXPECTED_ENDPOINTS` so `test_spec_documents_exactly_the_sidecar_endpoints` and `test_postman_collection_covers_every_sidecar_endpoint` require `/metrics` in the spec + Postman.
- `sidecar/tests/test_metrics_openapi.py` (new) — assert the spec documents `GET /metrics` with the exact nested response shape, and a round-trip: boot the real `make_handler` on a loopback port with a buffer populated from REAL `events.log_event` records, `GET /metrics`, and assert the real body's top-level + nested keys equal the spec's documented property names (spec⇄server contract, decision #12). Plus a README guard asserting `/metrics` is documented.
