---
id: 50c
title: Fix — a blocked answer must not be wrapped in the T50 citation split
status: ready-for-merge
depends_on: [50b]
branch: ticket/50c-blocked-answer-sectioning
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_blocked_answer_sectioning.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Bugfix follow-up to T50b. When the Week-1 verification gate BLOCKS a draft (V3 misattribution / V6 identifier leak / V7 status contradiction) it returns the safe fallback ("I can't verify that against the record.") in place of the unverified draft. The T50b citation split in `_gate_final_answer` still ran on that fallback: the original citations list carries a `guideline:` ref, so `_apply_citation_split` wrapped the fallback under a `## Patient record` header — leaking the split machinery onto a blocked answer (surfaced live in the card demo). The fix short-circuits `_gate_final_answer` on a `blocked` verdict, returning the safe fallback verbatim with no sectioning. A blocked answer has no surviving claims to separate, so this is always correct; the record-only and guideline paths are unaffected.

## Acceptance criteria
- [x] A blocked answer whose citations include a guideline ref is returned as the plain safe fallback — no `## Patient record` / `## Guideline evidence` headers, no unverified draft content.
- [x] The record-only blocked path still returns the fallback (unchanged).
- [x] T50/T50b gate tests + W1 verification regression stay green.

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_blocked_answer_sectioning.py`: a scripted turn that grounds a real guideline ref and emits a final answer tripping V6 (SSN leak) → the returned answer is the safe fallback, no section headers, no leaked SSN, no unverified draft text; plus the record-only blocked variant.
