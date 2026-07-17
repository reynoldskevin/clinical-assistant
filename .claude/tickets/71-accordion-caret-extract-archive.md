---
id: 71
title: Accordion caret indicator + archive cleared extractions as history items
status: todo
depends_on: [70]
branch: ticket/71-accordion-caret-extract-archive
base_branch: ticket/70-qa-history-accordions
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-accordion-extras.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 0
---

## Description
Two UX enhancements to the T70 Q&A history accordions, both in `agent-widget.js`
(dependency-free vanilla DOM, no innerHTML). First: each accordion heading gets a
small arrow/caret to the LEFT of the title so it reads as expandable, and the
caret reflects state (points right when collapsed, rotates to point down when
expanded). Second: when a document extraction is CLEARED by a SUBSEQUENT upload
(today it is silently wiped by `clearExtract()`), archive the previous extraction
into the SAME history accordion stack — the accordion heading is the uploaded
file's NAME and its collapsible body holds the rendered extracted-facts panel.
Nothing that was on screen is discarded; it moves into history alongside the Q&A
turns, chronologically above the live area.

Confirmed scope: the caret is purely a visual affordance built with
createElement/textContent (no icon font, no innerHTML); a new QUESTION does not
touch the extraction panel (extractions are archived only when a new UPLOAD clears
them); the first upload (no prior extraction) archives nothing; only a real facts
panel is archived (a plain status note such as "extraction unavailable" is not).

Implementation notes:
1. **Shared accordion builder.** Factor the T70 turn-building into a single helper
   used by both Q&A archiving and extraction archiving. Each heading is a
   `<button class="oe-ai-agent-turn-q">` containing, in order, a
   `<span class="oe-ai-agent-turn-caret" aria-hidden="true">` (the arrow glyph) then
   a `<span class="oe-ai-agent-turn-label">` holding the heading text; the body is a
   `<div class="oe-ai-agent-turn-a" hidden>` that receives the MOVED source nodes.
   Clicking the heading toggles `aria-expanded` and the body's `hidden` attribute
   (unchanged from T70). CSS rotates the caret when
   `.oe-ai-agent-turn-q[aria-expanded="true"]`.
2. **Extraction archive.** Track the file name that produced the currently-rendered
   extraction. On a new upload (after the no-file guard, alongside the existing
   `archiveTurn()` + `clearExtract()`), if a real facts panel is currently rendered,
   move it into a new accordion turn keyed by that file name and append it to the
   history BEFORE clearing the extraction box. A plain note (no `.card` panel) is
   not archived. The first upload archives nothing (no prior extraction).

The live Q&A/extraction render paths are otherwise unchanged.

## Acceptance criteria
- [ ] Every archived accordion heading contains a `.oe-ai-agent-turn-caret` element
  as its FIRST child (to the left of the title) plus a `.oe-ai-agent-turn-label`
  holding the heading text; the caret carries `aria-hidden="true"`.
- [ ] The heading text remains readable via `.oe-ai-agent-turn-label` (the T70
  behavior of the question staying visible in the heading is preserved).
- [ ] Clicking a heading still toggles `aria-expanded` and the body's `hidden`
  attribute (T70 interaction intact) — now on the caret-bearing heading.
- [ ] After an extraction has rendered a facts panel, triggering a SUBSEQUENT
  upload archives that extraction into the history: a `.oe-ai-agent-turn` whose
  `.oe-ai-agent-turn-label` shows the previous upload's FILE NAME and whose
  `.oe-ai-agent-turn-a` body contains the previously-rendered facts (e.g. the
  extracted value text); the live `.oe-ai-agent-extract` box no longer shows it.
- [ ] The archived extraction turn is collapsed by default (`aria-expanded="false"`,
  body `hidden`) and expands/collapses on click like a Q&A turn.
- [ ] The FIRST upload (no prior extraction) archives no extraction item; a prior
  extraction box holding only a status note (no `.card` facts panel) is not archived.
- [ ] Asking a new QUESTION does not archive or clear the extraction panel (only a
  new upload does).
- [ ] No regression: the T70 `agent-widget-history.test.js` and T69
  `agent-widget-clear.test.js` suites stay green; lint clean under `eslint --quiet`.

## Test plan (orchestrator authors these)
- unit (jsdom) `agent-widget-accordion-extras.test.js`:
  - caret: after archiving a Q&A turn, the heading's first child is
    `.oe-ai-agent-turn-caret` (aria-hidden), followed by a `.oe-ai-agent-turn-label`
    containing the question; clicking still toggles aria-expanded + body hidden.
  - extraction archive (fetch mocked to resolve token/upload/extract): upload
    `first.png`, let extraction render, then upload `second.png` → a history turn
    labelled `first.png` holds the first extraction's facts, collapsed by default,
    and the live extract box is cleared; expanding it reveals the facts.
  - first upload archives no extraction turn.
  - a new question does not create/clear an extraction archive.
