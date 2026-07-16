---
id: 69
title: Clear the answer area when a new upload is triggered
status: ready-for-merge
depends_on: []
branch: ticket/69-clear-answer-on-upload
base_branch: main
test_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-clear.test.js"
full_suite_command: "npx jest interface/modules/custom_modules/oe-module-ai-agent"
attempts: 0
---

## Description
Small UX consistency fix. When a clinician asks a NEW question, the answer/response
area (`.oe-ai-agent-answer`) is cleared synchronously on submit (via
`showThinking()`), so the stale previous answer never lingers under a new
interaction. Uploading a document does NOT do this today: the upload submit
handler clears the extraction panel (`clearExtract()`) but leaves the previous
question's answer sitting above it. The request is to mirror the ask behavior —
clear the answer area the moment a new upload is triggered.

The change is a one-liner in `agent-widget.js`'s upload submit handler: after the
"no file chosen" guard (so it only fires when an upload actually starts), clear
`answer.textContent`, alongside the existing `clearExtract()` / "Uploading..."
status. A submit with no file selected still shows "Choose a file to upload." and
must NOT wipe a prior answer.

This ticket also adds the repo's FIRST `agent-widget.js` jsdom test, so the
behavior is locked (there was no JS coverage for the widget before — the T68
banner and this both rendered/behaved with read-only verification).

## Acceptance criteria
- [x] Triggering an upload with a file selected clears `.oe-ai-agent-answer`
  (the previous answer/response) synchronously on submit, mirroring ask-submit.
- [x] Submitting the upload form with NO file selected does NOT clear the answer
  area (it only shows the "Choose a file to upload." status) — the clear happens
  only for a real upload, after the no-file guard.
- [x] The existing upload behavior is otherwise unchanged: `clearExtract()` still
  runs, the "Uploading..." status still shows, and the POST still fires.
- [x] No regression: the module's jest suite stays green.

## Test plan (orchestrator authors these)
- unit (jsdom) `interface/modules/custom_modules/oe-module-ai-agent/tests/agent-widget-clear.test.js`:
  loads the widget IIFE against a scaffolded DOM, seeds `.oe-ai-agent-answer` with
  a prior answer, and:
  - with a file in the file input → dispatch upload submit → assert
    `.oe-ai-agent-answer` is empty (and `fetch` was called for the upload).
  - with NO file → dispatch upload submit → assert the answer is preserved and the
    status reads the choose-a-file message.
  - sanity: a question submit also clears the answer (documents the mirrored
    behavior the change is matching).
