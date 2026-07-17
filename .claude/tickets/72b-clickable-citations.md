---
id: 072b
title: Clickable [Sn] citations in the answer → source modal
status: done
depends_on: [072a, 056h]
branch: ticket/72b-clickable-citations
base_branch: ticket/56h-client-pdf-geometry
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-citations.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 1
---

## Description
Frontend half of clickable answer citations. The `/ask/stream` `done` frame now carries a `citations` map (T72a: `{marker: {ref, type, section, text}}`). After the answer renders, wrap each `[Sn]` marker whose number is in that map as a small clickable control; clicking it opens a modal showing that citation's source (type + section + text) — the same modal style as the fact-citation [show source]. Markers with no matching source stay plain text. Stacked on T56h to reuse the modal and the reworked widget.

## Acceptance criteria
- [ ] When the `done` frame carries a non-empty `citations` map, each `[Sn]` marker in the rendered answer whose number `n` is a key becomes a clickable control (`button.oe-ai-agent-cite` with `data-n="n"`); its visible text still reads like the marker (e.g. `[S1]`).
- [ ] Clicking a citation control opens a modal (`.oe-ai-agent-source-modal`, hidden until opened) whose content shows that citation's source: its `text` (guideline snippet / record value) and `section`.
- [ ] Clicking a different citation swaps the modal to that source; a close button and backdrop click dismiss it (reuse the existing modal behavior).
- [ ] A marker whose number is NOT in the citations map (or when there is no citations map) stays plain text — not clickable.
- [ ] All DOM via createElement/textContent — no innerHTML. The answer text is otherwise unchanged; existing ask/answer/history behavior is preserved.

## Test plan (orchestrator authors these)
- `tests/agent-widget-citations.test.js` — drive the streaming ask flow (mocked SSE: an `answer` frame with `[S1]`/`[S2]` then a `done` frame with the citations map); assert the markers become clickable, the modal shows the right source per marker, and unmapped markers stay plain.
