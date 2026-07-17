---
id: 056b
title: Card image preview + citation bounding-box overlay render
status: done
depends_on: [056a]
branch: ticket/56b-card-bbox-overlay
base_branch: ticket/56a-citation-bbox-locator
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-bbox.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 1
---

## Description
Second half of T56. Render the citation bounding-box overlay on the agent card, consuming the `citation_boxes` + `page_width`/`page_height` contract T56a added to the `/extract` response. Today the card shows only the extracted facts; this adds a preview of the uploaded document IMAGE with one positioned overlay box per located citation, so a clinician can see exactly where on the page each extracted fact came from. The preview uses an object URL from the uploaded image file (image uploads only — PDFs/non-images get no preview, gracefully); boxes are positioned as percentages of the page dimensions so they scale with the displayed image. Stacked on T56a for the shared payload shape.

## Acceptance criteria
- [ ] When an extraction response carries `citation_boxes` + `page_width`/`page_height` AND an image preview URL is available, the card renders a positioned preview: an `<img class="oe-ai-agent-doc-image">` (src = the preview URL) inside a relatively-positioned container, plus one absolutely-positioned `.oe-ai-agent-citation-box` per box.
- [ ] Each overlay box is positioned by PERCENTAGE of the page dimensions: `left = x/page_width`, `top = y/page_height`, `width = w/page_width`, `height = h/page_height` (as percentages), so it scales with the rendered image.
- [ ] When the response has no `citation_boxes` (or an empty list), no preview/overlay is rendered — the existing facts panel is unchanged.
- [ ] A non-image upload (e.g. a PDF) yields no preview even if boxes are present (no object URL created for non-images).
- [ ] All DOM is built via createElement/textContent (no innerHTML); overlay never breaks the existing facts panel, file-to-chart button, or wrong-chart/duplicate behavior.

## Test plan (orchestrator authors these)
- `interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-bbox.test.js` — jsdom: upload an image → extract returns citation_boxes → assert the preview image + percentage-positioned overlay boxes; and the no-boxes case renders no overlay.
