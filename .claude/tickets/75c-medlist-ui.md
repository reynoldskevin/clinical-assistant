---
id: 075c
title: med_list UI — doc-type option + widget field rendering
status: ready-for-merge
depends_on: []
branch: ticket/75c-medlist-ui
base_branch: main
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-medlist.test.js && docker exec development-easy-openemr-1 bash -lc 'cd /var/www/localhost/htdocs/openemr && vendor/bin/phpunit -c phpunit-isolated.xml --filter AgentCardTest'"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 1
---

## Description
Surface the `med_list` document type in the card UI: add a "Medication List" option to the upload doc-type `<select>` (`src/Ui/AgentCard.php`) and a `med_list` entry to the widget's `FACT_FIELDS` field-order map (`public/agent-widget.js`) so a medication-list extraction renders its `medications` + `source_citation` fields and can be filed to the chart via the existing (doc-type-agnostic) persist-button flow. No new persist logic — the widget already POSTs the fact envelope and renders the persister's `filed`/`total` response.

## Acceptance criteria
- [ ] `src/Ui/AgentCard.php` doc-type `<select>` includes `<option value="med_list">Medication List</option>` alongside Lab PDF and Intake form.
- [ ] `agent-widget.js` `FACT_FIELDS` gains `med_list: ['medications', 'source_citation']`, so a `med_list` extract response renders its fields in that order in the extracted-facts panel.
- [ ] The existing extract-render + persist-to-chart flow works unchanged for `med_list`: after a `med_list` extraction the fact fields render, and clicking "file to chart" POSTs to persist.php and shows the "Filed N facts" confirmation from the response.
- [ ] No regression to the `lab_pdf`/`intake_form` render/persist behaviour or the other widget tests.

## Test plan (orchestrator authors these)
- Extend `interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-persist.test.js` (or a focused new `agent-widget-medlist.test.js`) — drive the upload→extract→persist flow for `doc_type='med_list'` with a mocked `/extract` returning a `MedicationListFact` (`{medications, source_citation}`) and a mocked persist.php returning `{ok, doc_type:'med_list', total, filed}`; assert the medications field renders and the persist confirmation appears.
