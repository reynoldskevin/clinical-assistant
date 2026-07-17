---
id: 056d
title: Click-to-reveal per-fact citation source (rework the always-on overlay)
status: done
depends_on: [056a, 056b, 056c]
branch: ticket/56d-click-to-reveal-citation
base_branch: ticket/56c-bbox-demo-provider
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-bbox.test.js && docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_bbox_locator.py tests/test_bbox_demo_provider.py -q"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent && docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
UX correction for T56b: instead of drawing all citation boxes at once on an always-visible document preview, make each extracted fact CLICKABLE and reveal only THAT fact's highlighted source on demand. The `/extract` response's `citation_boxes` becomes a per-field map (`{field: [boxes]}`) so the card can show a single fact's source; clicking a cited fact toggles a document preview overlaying only that fact's box(es). Supersedes the flat `citation_boxes` list (T56a/T56c) and the always-on overlay render (T56b).

## Acceptance criteria
- [ ] `default_extract_builder`'s geometry-wired box computation sets `citation_boxes` to a per-field MAP `{field_name: [ {x,y,w,h}, ... ]}` — one entry per fact field whose value locates to ≥1 box (fields with no located box are omitted). `page_width`/`page_height` still included. No geometry provider → no `citation_boxes` (unchanged).
- [ ] The card renders NO boxes and NO visible preview initially — the document preview is hidden until a fact is clicked.
- [ ] Each fact whose field appears in `citation_boxes` is rendered as a clickable control (identifiable via `data-field` + an `oe-ai-agent-fact-cite` class); facts with no boxes are NOT clickable.
- [ ] Clicking a cited fact reveals the document preview (`<img class="oe-ai-agent-doc-image">`) with ONLY that field's box(es) drawn (percentage-positioned), replacing any previously shown field's boxes.
- [ ] Clicking the currently-active fact again hides the preview (toggle).
- [ ] No `citation_boxes` (or non-image upload) → no clickable facts and no preview; existing facts panel, file-to-chart, wrong-chart, and duplicate behavior unchanged. All DOM via createElement/textContent — no innerHTML.

## Test plan (orchestrator authors/updates these)
- `tests/agent-widget-bbox.test.js` — rewritten for click-to-reveal (hidden until click, per-fact toggle, only that fact's boxes, non-cited facts not clickable).
- `tests/test_bbox_locator.py` + `tests/test_bbox_demo_provider.py` — updated to the per-field `citation_boxes` map.
