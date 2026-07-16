---
id: 70
title: Q&A history — collapsible accordions instead of clearing prior answers
status: ready-for-merge
depends_on: [69]
branch: ticket/70-qa-history-accordions
base_branch: main
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-history.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 0
---

## Description
Today a new question (T69: or a new upload) CLEARS the previous answer — the prior
turn is lost. The request is to keep a running Q&A history instead: each completed
turn moves into a collapsible accordion whose QUESTION is visible at all times as
the heading, with the ANSWER revealed when the heading is clicked. The accordions
stack chronologically ABOVE the live area where new responses appear.

Confirmed decisions: an UPLOAD archives the current turn too (nothing is silently
discarded); order is CHRONOLOGICAL (oldest at the top, newest turn directly above
the live answer area).

All in `agent-widget.js` (dependency-free vanilla DOM, no Bootstrap collapse JS):

1. **History container.** On wiring, create a `.oe-ai-agent-history` container and
   insert it as a sibling immediately BEFORE the live `.oe-ai-agent-answer` element,
   so archived turns appear above where new responses render.
2. **Track the current turn's question.** Keep the question text that produced the
   answer currently in the live area (set on question submit; the live area streams
   that turn's answer as before).
3. **Archive-on-clear.** Replace the "clear the live answer" behavior (both the
   new-question path — previously `showThinking()` implicitly clearing — and the
   upload path — T69's `answer.textContent = ''`) with an `archiveTurn()` step that:
   - if a current question AND live answer content exist, builds an accordion turn
     and MOVES the live answer's rendered DOM into it (preserving tables/lists),
     appending it to the history (chronological → newest last, directly above live);
   - always leaves the live answer area EMPTY afterward and resets the tracked
     question (so a headless/again-cleared area still ends empty — T69 semantics
     preserved when there is no question to attribute).
4. **Accordion contract + interaction.** Each turn is a `.oe-ai-agent-turn`
   containing a `<button class="oe-ai-agent-turn-q">` heading (always shows the
   question text; `aria-expanded` reflects state, default `"false"`) and a
   `.oe-ai-agent-turn-a` body holding the answer DOM (`hidden` attribute when
   collapsed, default collapsed). Clicking the heading toggles: `aria-expanded`
   flips and the body's `hidden` attribute is added/removed. All text set via
   textContent / moved nodes — no HTML injection.

The live streaming/render path is otherwise unchanged; only the previous turn's
disposal changes from "discard" to "archive into history".

## Acceptance criteria
- [x] A `.oe-ai-agent-history` container is created and positioned as a sibling
  BEFORE `.oe-ai-agent-answer` (archived turns render above the live area).
- [x] Asking a second question archives the FIRST turn: a `.oe-ai-agent-turn` is
  appended to the history whose `.oe-ai-agent-turn-q` heading shows the first
  question and whose `.oe-ai-agent-turn-a` body holds the first answer; the live
  answer area no longer shows that answer.
- [x] The archived turn is COLLAPSED by default: the heading is a button with
  `aria-expanded="false"` and the body has the `hidden` attribute. Clicking the
  heading expands it (`aria-expanded="true"`, body no longer `hidden`); clicking
  again collapses it.
- [x] The question text remains visible in the heading at all times (collapsed or
  expanded).
- [x] Chronological order: with multiple archived turns, the oldest is the first
  child and the newest is the last child of the history (nearest the live area).
- [x] Uploading a document archives the current turn too (same accordion, keyed by
  its question) and leaves the live answer empty — nothing is silently discarded.
- [x] The first question (no prior turn) creates NO history item; when there is no
  tracked question, the live area is still simply cleared (T69 semantics intact).
- [x] No regression: the T69 `agent-widget-clear.test.js` suite stays green; lint
  clean under `eslint --quiet`.

## Test plan (orchestrator authors these)
- unit (jsdom) `interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-history.test.js`:
  loads the widget IIFE against a scaffolded DOM, mocks `fetch` (never resolves),
  drives real submit handlers, and simulates each turn's answer by setting the live
  answer content between submits. Cases: second question archives the first turn
  (heading=Q1, body=A1, collapsed by default, live area cleared); clicking the
  heading expands then collapses; chronological order across three turns; upload
  archives the current turn and clears the live area; first question creates no
  history item; history container sits before the live answer element.
