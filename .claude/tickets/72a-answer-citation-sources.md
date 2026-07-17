---
id: 072a
title: Return per-marker citation sources in the /ask response
status: tests-authored
depends_on: []
branch: ticket/72a-answer-citation-sources
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_citation_sources.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Backend half of making the answer's `[Sn]` citations clickable-to-source (T72b renders them). The agent already knows each surviving `[Sn]` marker's ref and its backing record (`by_number` + `retrieved_data`), but the `/ask` response only returns `{answer, correlation_id}`. Add a pure `build_citation_sources(citations, retrieved_data)` that maps each grounded marker number to `{ref, type, section, text}` (guideline snippet + title/section, or a chart record summary — reusing `_citation_for`'s fields), have the agent expose the map as `citation_sources` after composing an answer, and include it in the `/ask` and `/ask/stream` responses.

## Acceptance criteria
- [ ] `build_citation_sources(citations, retrieved_data)` returns a dict keyed by marker number (string) → `{ref, type, section, text}`: guideline refs → `type="guideline"`, `text` = the snippet, `section` = the title/section; chart refs → `type="record"`, `text` = the record value (drug/title/value). A ref with no backing record is omitted.
- [ ] `ClaudeAgent` exposes `citation_sources` (a dict), defaulting to `{}`, populated for the SURVIVING (grounded) markers whenever it composes an answer — on both `run` and `run_turn` paths.
- [ ] `process_ask` includes `citations` in the 200 response when the agent has a non-empty `citation_sources`; omits the key when empty.
- [ ] The streaming path (`stream_ask`) carries the same `citations` map in its terminal `done` frame.
- [ ] No change to the answer text or existing response fields; JSON-serializable.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_citation_sources.py` — the pure builder (guideline/record/omit), the agent exposing `citation_sources` after `_apply_citation_split`, and `process_ask` including/omitting `citations`.
