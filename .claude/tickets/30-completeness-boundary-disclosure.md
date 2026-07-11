---
id: 30
title: Completeness-boundary disclosure — surface tool-budget truncation
status: ready-for-merge
depends_on: []
branch: ticket/30-completeness-boundary-disclosure
base_branch: main
test_command: "python -m pytest sidecar/tests/test_completeness_disclosure.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
The agent loop bounds work at `max_tool_calls` (8): once spent, tools are
withdrawn and the model is forced to answer on whatever it has gathered. Today
that truncation is SILENT — the physician gets a confident-looking answer with no
signal that the agent stopped looking. The brief (Speed vs. Completeness)
requires the tradeoff be explicit: *what you defer, and how you communicate it.*
Surface the completeness boundary — the same "no silent caps" principle already
applied to the eval sweep.

## Acceptance criteria
- [ ] When the final answer is produced because the tool budget was exhausted
      (`tool_calls_made >= max_tool_calls` at the no-more-tool-uses branch), the
      returned answer carries a partiality disclosure (a plain, digit-free,
      citation-free notice appended AFTER the verification gate so it cannot
      corrupt grounding). The disclosure text contains the phrase "lookup limit".
- [ ] In that same case, when `on_event` is supplied, a truncation event
      `{"type": "truncated", "reason": "tool_budget"}` is emitted (once).
- [ ] When the model answers naturally while still under budget, NO disclosure is
      appended and NO truncated event is emitted (byte-for-byte today's answer).
- [ ] Backward compatible: with `on_event=None`, an exhausted-budget turn still
      appends the disclosure and does not crash.
- [ ] The clinical answer text is preserved — the disclosure is additive, not a
      replacement (the gated answer still appears, with the notice appended).

## Test plan (orchestrator authors these)
- unit: `sidecar/tests/test_completeness_disclosure.py`
  - budget exhausted (small max_tool_calls) -> answer has "lookup limit" + a
    `truncated` event
  - natural answer under budget -> no notice, no truncated event
  - exhausted with on_event=None -> notice present, no crash
  - clinical text preserved alongside the appended notice
