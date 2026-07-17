---
id: 056e
title: Citation source — small [show source] control + modal overlay
status: done
depends_on: [056d]
branch: ticket/56e-source-modal
base_branch: ticket/56d-click-to-reveal-citation
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-bbox.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 1
---

## Description
UX refinement of T56d. Instead of the whole fact row being clickable, each cited fact gets a small **[show source]** control (smaller font) that opens its highlighted source. And the document preview is shown in a **modal overlay** (centered, with a dismissable backdrop) rather than inline below the facts. Clicking a fact's [show source] opens the modal with only that fact's box(es); a close button, the backdrop, or clicking the same [show source] again dismisses it. JS-only — the per-field `citation_boxes` response contract from T56d is unchanged.

## Acceptance criteria
- [ ] Each fact whose field appears in `citation_boxes` renders a small control `button.oe-ai-agent-show-source` (with `data-field` = the raw field key) labelled "show source"; the fact's value text is still shown. Facts with no boxes get no control.
- [ ] The whole `<dd>` row is NOT itself the click target — only the small control opens the source (the `<dd>` has no `data-field`/`role=button`).
- [ ] The source preview is a modal overlay `div.oe-ai-agent-source-modal`, hidden by default, containing an `<img class="oe-ai-agent-doc-image">` with the percentage-positioned overlay boxes and a close control `button.oe-ai-agent-source-close`.
- [ ] Clicking a fact's [show source] shows the modal with ONLY that field's box(es); clicking another fact's [show source] swaps to that field's box(es).
- [ ] The modal is dismissed by the close button, by clicking the backdrop, or by clicking the active fact's [show source] again (toggle); on dismiss the overlay boxes are cleared.
- [ ] No `citation_boxes` (or non-image upload) → no [show source] controls and no modal; existing facts panel, file-to-chart, wrong-chart, and duplicate behavior unchanged. All DOM via createElement/textContent — no innerHTML.

## Test plan (orchestrator authors/updates these)
- `tests/agent-widget-bbox.test.js` — rewritten for the [show source] control + modal (small control per cited fact, modal hidden until opened, only-that-fact's boxes, swap, close/backdrop/toggle dismiss, non-cited/no-boxes/PDF).
