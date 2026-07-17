---
id: 056g
title: Render uploaded PDFs in the card (pdf.js) so lab overlays work
status: done
depends_on: [056e, 056f]
branch: ticket/56g-pdf-render
base_branch: ticket/56f-lab-geometry
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-bbox.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 1
---

## Description
Front-end half of extending the citation overlay to lab PDFs. The card previews images today; PDFs can't render as an `<img>`, so lab uploads got no preview. Add a PDF renderer: the widget resolves the preview through a `window.OE_AI_AGENT_PDF_RENDER(file) -> Promise<url>` seam (kept out of the widget so it stays jsdom-testable), and a separate `pdf-preview.js` glue file wires that seam to the vendored pdf.js (`public/vendor/pdfjs/`), rendering the uploaded PDF's first page to an image the overlay draws on. Included by `AgentCard.php`. With a renderer available, a PDF upload gets the same [show source]/modal citation UX as images; with none, it degrades gracefully to no preview.

## Acceptance criteria
- [ ] The widget's preview resolution is async and PDF-aware: for `application/pdf` uploads it uses `window.OE_AI_AGENT_PDF_RENDER(file)` (a `Promise<url>`); for images it keeps using an object URL; anything else → no preview.
- [ ] With a renderer seam present, a PDF upload enables the per-fact [show source] controls and the modal shows the rendered page (`img.oe-ai-agent-doc-image` src = the renderer's URL) with only the clicked fact's boxes. `URL.createObjectURL` is NOT used for PDFs.
- [ ] With no renderer seam present, a PDF upload degrades to no controls and no preview (existing facts panel unchanged) — no error.
- [ ] `public/pdf-preview.js` defines `window.OE_AI_AGENT_PDF_RENDER` by lazily importing the vendored pdf.js and rendering page 1 of the file to a data URL (canvas). `AgentCard.php` includes it (cache-busted) alongside `agent-widget.js`.
- [ ] `pdfjs-dist` pinned in devDependencies; `public/vendor/pdfjs/pdf.min.mjs` + `pdf.worker.min.mjs` vendored. Image-upload behavior and all existing widget tests unchanged. No innerHTML.

## Test plan (orchestrator authors/updates these)
- `tests/agent-widget-bbox.test.js` — PDF-render seam: stubbed renderer → controls + modal work with the rendered page URL; no renderer → graceful no-preview. Image tests unchanged.
