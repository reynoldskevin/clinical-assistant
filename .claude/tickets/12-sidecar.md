---
id: 12
title: Sidecar scaffold + Claude API single-tool loop (first turn)
status: tests-authored
depends_on: [09]
branch: ticket/12-sidecar
base_branch: main
test_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
full_suite_command: "etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 0
---

## Description
The external agent sidecar's core: a `ClaudeAgent` that runs a manual tool-use loop
against the Claude API (default `claude-opus-4-8`) with a single tool,
`get_patient_summary`, backed by the T09 boundary. Built for testability — the
Claude message-creator and the boundary caller are INJECTED, so unit tests use fakes
(no SDK import in the core, no live API calls). Streaming/SSE is deferred to T25;
this is the non-streaming first turn.

## Acceptance criteria
- [ ] `ClaudeAgent(message_creator, boundary, model='claude-opus-4-8', max_tokens=4096)`
      in `sidecar/agent.py`. The core module does NOT import `anthropic`.
- [ ] `run(question: str, pid: int) -> str` runs the manual loop: call the creator with
      the tool catalog; on a `tool_use` block for `get_patient_summary`, call
      `boundary(pid)`, append the assistant turn + a `tool_result` (matching
      `tool_use_id`), and loop; on `end_turn`, return the concatenated text.
- [ ] The `get_patient_summary` tool is passed to the creator (name, description,
      object `input_schema`).
- [ ] SECURITY: the tool takes no patient argument — the sidecar always calls
      `boundary(pid)` with the FIXED session pid; a model-supplied pid is ignored, so
      the model cannot redirect to another patient.
- [ ] Loop is bounded (max iterations) so a misbehaving model can't spin forever.

## Test plan (orchestrator authors these — LOCKED)
- unit (`sidecar/tests/test_agent.py`, injected fakes): single-tool turn returns final
  text + boundary called with the session pid + a tool_result fed back; no-tool direct
  answer (boundary untouched); model-supplied pid is ignored (fixed pid used); tool
  catalog well-formed; model + tools passed to the creator.

## Notes
Production wiring (a factory that imports the anthropic SDK and builds a real
message-creator + an HTTP boundary client hitting T09) is a thin, separately-tested
deliverable; the injected core is what's unit-locked here.
