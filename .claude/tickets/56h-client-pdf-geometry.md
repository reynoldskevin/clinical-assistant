---
id: 056h
title: Client-side PDF citation geometry from the pdf.js text layer
status: tests-authored
depends_on: [056g]
branch: ticket/56h-client-pdf-geometry
base_branch: ticket/56g-pdf-render
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-bbox.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 0
---

## Description
Fix lab-PDF box mislocation robustly. The server demo geometry was served for any `lab_pdf` upload, so a PDF that wasn't the exact demo doc mislocated. Instead, for PDF uploads derive word geometry from the PDF's OWN text layer via pdf.js (`getTextContent`) and locate citation boxes CLIENT-SIDE against the actual rendered page — works for any text-based lab PDF, no server geometry, no document mismatch. The render seam now returns `{url, words, page_width, page_height}`; the widget locates each extracted fact value in `words`. Image uploads keep using the server `citation_boxes` (demo geometry). The demo lab report is regenerated as a text-based PDF so it has a text layer.

## Acceptance criteria
- [ ] The demo lab report (`synthetic_lab_report_demo.pdf`) is a text-based PDF (has a text layer pdf.js can read).
- [ ] `pdf-preview.js`'s `window.OE_AI_AGENT_PDF_RENDER(file)` resolves to `{url, words, page_width, page_height}` — the rendered page URL PLUS per-word geometry (text runs split into words) in the rendered page's pixel space.
- [ ] The widget locates fact values in the PDF's `words` client-side (a JS port of the box locator: normalized contiguous token match, one union box per line) and drives the SAME per-fact [show source] + modal UX; only fact values found in the text layer get a control.
- [ ] Image uploads are unchanged — they use the server `citation_boxes` map.
- [ ] With no PDF renderer available, a PDF upload degrades to no controls (no error). All DOM via createElement — no innerHTML.

## Test plan (orchestrator authors/updates these)
- `tests/agent-widget-bbox.test.js` — image path (server boxes) unchanged; PDF path stubs the seam returning `{url, words, page_width, page_height}` and asserts the widget locates a fact value in `words` and boxes it; no-renderer degrades.
