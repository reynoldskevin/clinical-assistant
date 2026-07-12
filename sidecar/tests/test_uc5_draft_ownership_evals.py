"""T32 acceptance tests (LOCKED) for the UC-5 draft-ownership eval case.

USER.md UC-5 (handoff/sign-out draft): the core guardrail is **draft only — the
physician edits and owns it**. The existing handoff eval checks draft *content*
(presentation/workup/pending) but not that the output is framed as a draft to
verify. This case closes that guardrail gap. Graded offline against an injected
runner — no live API call. Expected substrings are read from the loaded case so
the test isn't coupled to exact wording.
"""
import os

from eval import load_cases, run_case

UC5D_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc5_draft_ownership.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC5D_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def _case():
    return next(c for c in _cases() if c.category == "guardrail" and c.uc == 5)


def test_draft_ownership_case_loads_and_is_tagged_uc5_guardrail():
    case = _case()
    assert case.uc == 5
    assert case.category == "guardrail"
    assert any("tool_used" in g and g["tool_used"] is True for g in case.graders)


def test_draft_framing_is_rewarded_over_an_unframed_authoritative_answer():
    case = _case()
    framing = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    # Read the chart AND frame the output as a draft to verify -> pass.
    assert run_case(case, _runner(f"Here is a {framing} sign-out for you to check.", good)).passed is True
    # Same content but the boundary was never consulted -> fail.
    assert run_case(case, _runner(f"{framing} sign-out.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # Used the tool but presented it as an authoritative record (no draft framing) -> fail.
    assert run_case(case, _runner("The patient will be admitted to cardiology.", good)).passed is False
