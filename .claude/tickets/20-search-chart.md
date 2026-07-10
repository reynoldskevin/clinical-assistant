---
id: 020
title: Tool — search_chart (free-text notes search, snippets-only) (+ eval case)
status: tests-authored     # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [019]
branch: ticket/20-search-chart
base_branch: ticket/19-get-medications   # STACKED off T19 (unmerged) — shares the enum/interface/factory; see skill decision #2
test_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml tests/Tests/Isolated/Modules/AiAgent  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "docker exec -w /var/www/localhost/htdocs/openemr development-easy-openemr-1 ./vendor/bin/phpunit -c phpunit-isolated.xml  &&  etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description

Add the `search_chart` tool: full-text search over the patient's free-text notes,
returning snippet rows (never whole documents), on the existing multi-tool read
boundary. This is the tool for content the structured tools don't expose — the
actual clinical narrative in `pnotes` and `form_soap`.

## Design (per ARCHITECTURE.md §2.6)

- **`search_chart({query, limit?})`** — searches the patient's note sources for
  `query` and returns `[{ref, source_type, date, snippet}]`. **Snippets only** —
  the snippet is truncated (≤ 300 chars), never the whole document (minimum-necessary).
- **Sources (scoped to note free-text; structured data is covered by the other tools;
  document storage is out of scope):**
  - `pnotes` (title/body) → `source_type = 'note'`
  - `form_soap` (subjective/objective/assessment/plan) → `source_type = 'soap'`
- **pid-scoped** on `pnotes.pid` / `form_soap.pid`, `query` matched with a BOUND
  `LIKE '%…%'` (never interpolated), most-recent-first, capped by `limit` (default 20).
  An empty/whitespace query returns `[]`.
- Reuses the boundary shape: one `ChartOperation` case (`search_chart`) + one provider
  method + one match arm + one ToolSpec. `query` is a REQUIRED model input; `limit`
  optional. Contract-test the sidecar↔read.php bare-array payload (decision #12).

## Acceptance criteria
- [ ] `ChartOperation` gains `search_chart` (6th op); interface gains `searchChart(int $pid, string $query, int $limit): array`; `ChartReadEndpoint` dispatches it via exhaustive match, reading `query` + `limit` (default 20) from params.
- [ ] `searchChart` returns `{ref, source_type, date, snippet}` rows from `pnotes` (`note`) + `form_soap` (`soap`), pid-scoped; snippet truncated (≤300); empty query → `[]`; cross-pid isolation holds; `limit` caps results.
- [ ] Sidecar: `ChartBoundary.search_chart(pid, query, limit=20)` POSTs `{op:"search_chart", pid, params:{query, limit}}` and accepts a BARE ARRAY (decision #12); `build_search_tool` ToolSpec requires `query`, optional `limit`, dispatches with the fixed pid.
- [ ] UC-7 eval case requires tool use + grounded note content.
- [ ] All prior locked tests still pass (with the ChartOperationTest/ChartReadEndpointTest updates for the 6th op).
- [ ] **MR carries `Depends on: !<T19-MR>` — merge T19 first** (stacked).

## Test plan (LOCKED — authored)
- PHP DB-backed `ChartReadServiceSearchTest`: find pnote by body / soap note, cross-pid isolation, limit cap, empty query → [], snippet truncation.
- PHP updates: `ChartOperationTest` (6 ops), `ChartReadEndpointTest` (fake `searchChart` + dispatch with query/limit + default limit; cross-pid loop iterates `cases()`).
- Sidecar `test_search_tool`: boundary POST shape + default limit + bare-array contract + ToolSpec (query required) dispatch.
- Eval `test_uc7_evals` + `evals/uc7.yaml`.
