"""T33 guard tests (LOCKED) — system-prompt task-framing for UC-4 / UC-5.

The UC-4 (longitudinal-pattern) and UC-5 (draft-ownership) eval cases only pass on
the LIVE sweep if the agent actually synthesizes a pattern across prior encounters
and frames handoffs as drafts to verify. That behaviour is driven by the system
prompt. These are guard tests: they pin the two instructions into the prompt so a
future edit can't silently drop them (real behavioural validation is the live
eval sweep, not these). Deterministic; inspect the constant only.
"""
from agent import _SYSTEM_PROMPT

_PROMPT = _SYSTEM_PROMPT.lower()


def test_prompt_instructs_longitudinal_pattern_synthesis():
    # UC-4: synthesize the pattern across prior encounters, not just list them.
    assert "pattern" in _PROMPT
    assert "prior" in _PROMPT or "previous" in _PROMPT or "recurrent" in _PROMPT


def test_prompt_instructs_explicitness_about_retrievable_history():
    # UC-4 guardrail: be explicit about what prior history could / could not be found.
    assert "could not" in _PROMPT or "couldn't" in _PROMPT or "unable to" in _PROMPT


def test_prompt_instructs_handoff_draft_framing():
    # UC-5: present a sign-out / handoff as a draft the physician verifies and owns.
    assert "draft" in _PROMPT
    assert "sign-out" in _PROMPT or "handoff" in _PROMPT


def test_prompt_still_carries_grounding_and_data_quality_contract():
    # Guard against an accidental rewrite dropping the existing contract.
    assert "openemr:_absence" in _SYSTEM_PROMPT
    assert "empty != absent" in _PROMPT
    assert "citations" in _PROMPT


def test_prompt_instructs_same_line_distinct_marker_citation():
    # V3 (contradicts_record) blocks when an [Sn] marker lands in a sentence that
    # names no specific record (e.g. a bare "Active medications: [S1]" lead-in).
    # The prompt must steer each marker onto the SAME line as the record it names,
    # give each record a distinct marker, and keep markers off name-less headings,
    # so a model (esp. a smaller/faster one) does not intermittently trip the gate.
    assert "same sentence or list item" in _PROMPT
    assert "do not reuse one marker" in _PROMPT
    assert "names no specific record" in _PROMPT
