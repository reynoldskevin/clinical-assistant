---
id: 77
title: Lab trend chart widget (get_results → inline SVG time series)
status: tests-authored
depends_on: []
branch: ticket/77-lab-trend-chart
base_branch: main
test_command: "node_modules/.bin/jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-labtrends.test.js && docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && AI_DB_HOST=mysql ./vendor/bin/phpunit tests/Tests/Isolated/Modules/AiAgent/Ui/AgentCardTest.php tests/Tests/Isolated/Modules/AiAgent/Service/ChartReadServiceResultsTest.php'"
full_suite_command: "node_modules/.bin/jest && docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && AI_DB_HOST=mysql ./vendor/bin/phpunit --group isolated'"
attempts: 0
---

## Description
Add a "Lab trends" chart to the AI Clinical Co-Pilot card that visualizes a patient's lab results over time. Stretch goal #9. The existing `get_results` boundary op (`read.php`) already returns time-series-ready rows (`result_text`, `result`, `units`, `range`, `abnormal`, `date`) — the same rows the lab persister writes — so no PHP data-layer change is needed. On demand (a "Lab trends" button in the card), the browser mints its pid-scoped JWT (the same one it already mints for `/ask`) and POSTs `read.php {op:'get_results', pid}`, groups the numeric results by test name, and renders a dependency-free inline SVG line chart for a user-selected test (a series selector lists every test), with abnormal points marked and the reference range shown. The module stays front-end-dependency-free (vanilla JS + SVG; no chart library).

## Acceptance criteria
- [ ] AC1 — `AgentCard::render()` emits an on-demand trigger (`.oe-ai-agent-trends-btn`, a real `<button type="button">`, not a form submit) and an empty chart container (`.oe-ai-agent-trends`).
- [ ] AC2 (contract) — clicking the trends button mints a token via `token.php`, then POSTs `read.php` with method POST, header `Authorization: Bearer <jwt>`, and JSON body `{op:'get_results', pid:<int from data-pid>, params:{}}`. The jsdom mock's `read.php` response is the shared fixture `tests/fixtures/get_results_contract.json`, whose row key-set is pinned on the PHP producer side by `ChartReadServiceResultsTest` (a producer shape change breaks the consumer fixture).
- [ ] AC3 (transform) — results are grouped by `result_text` into one series per test; a row whose `result` is non-numeric OR whose `date` is unparseable is dropped; the series selector lists only tests that have ≥1 numeric+dated point, sorted by name; each series' points are ordered ascending by date.
- [ ] AC4 (render) — the container renders a `<select class="oe-ai-agent-trends-select">` (one `<option>` per numeric test) and an `<svg class="oe-ai-agent-trends-chart">`; each plotted point is an element `.oe-ai-agent-trends-point` carrying `data-date` (ISO) and `data-value` (number); an abnormal point is distinguished (`data-abnormal="1"`); the selected test's reference range is shown (`.oe-ai-agent-trends-range`). Changing the selector re-renders the points for the newly-selected test. All DOM is built via `createElement`/`createElementNS` + `textContent`/`setAttribute` — no `innerHTML` of server data.
- [ ] AC5 (states) — when `get_results` yields no numeric series, the container shows a friendly "no numeric lab results" message and NO `<svg>`; when `read.php` fails (`!ok` or network error), the container shows a generic, non-leaky error message and NO `<svg>`.

## Test plan (orchestrator authors these; LOCKED)
- php-isolated: extend `tests/Tests/Isolated/Modules/AiAgent/Ui/AgentCardTest.php` — trends button (`type="button"`) + empty `.oe-ai-agent-trends` container present. (AC1)
- php-isolated (contract, DB-backed): extend `ChartReadServiceResultsTest` — the real `getResults` row exposes every key in `tests/fixtures/get_results_contract.json` (producer pins the shared shape). (AC2)
- js-jsdom (new): `interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-labtrends.test.js` — click → token+read.php fetch shape (AC2); grouping/selector + point count/order + abnormal flag from the fixture (AC3/AC4); selector re-render (AC4); empty + error states (AC5).
- shared fixture (new): `interface/modules/custom_modules/oe-module-ai-agent/tests/fixtures/get_results_contract.json`.
