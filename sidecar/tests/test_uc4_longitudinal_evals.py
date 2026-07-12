"""T32 acceptance tests (LOCKED) for the UC-4 longitudinal-pattern eval cases.

USER.md UC-4 (longitudinal / frequent-utilizer): the distinctive value is
synthesizing a PATTERN across multiple prior encounters ("already had three
negative CTs for this pain"), not merely listing that encounters exist; and the
guardrail is being explicit about prior workups it could/couldn't find (no
fabricated history). These two cases close that gap. Graded offline against an
injected runner — no live API call. Expected substrings are read from the loaded
case so the test isn't coupled to exact wording.
"""
import os

from eval import load_cases, run_case

UC4L_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc4_longitudinal.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC4L_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def _pattern_case():
    return next(c for c in _cases() if c.category == "synthesis" and c.uc == 4)


def _absence_case():
    return next(c for c in _cases() if c.category == "absence" and c.uc == 4)


def test_longitudinal_pattern_case_loads_and_is_tagged_uc4_synthesis():
    case = _pattern_case()
    assert case.uc == 4
    assert case.category == "synthesis"
    assert any("tool_used" in g and g["tool_used"] is True for g in case.graders)


def test_pattern_case_rewards_grounded_synthesis_over_hollow_answer():
    case = _pattern_case()
    term = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    # Read the chart AND surface a longitudinal pattern term -> pass.
    assert run_case(case, _runner(f"On {term} visits the same workup was already done.", good)).passed is True
    # Same content but the boundary was never consulted -> fail.
    assert run_case(case, _runner(f"There was a {term} workup.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # Used the tool but produced no pattern language -> fail.
    assert run_case(case, _runner("The patient came in today.", good)).passed is False


def test_absence_case_loads_and_is_tagged_uc4_absence():
    case = _absence_case()
    assert case.uc == 4
    assert case.category == "absence"


def test_absence_case_rewards_honest_no_prior_over_fabrication():
    case = _absence_case()
    term = _contains_any(case)[0]

    # Honestly states there is no prior study documented -> pass.
    assert run_case(case, _runner(f"There is {term} such study.", {"tool_calls": 1, "tool_failures": 0})).passed is True
    # Fabricates a prior study instead of flagging the gap -> fail (no absence phrase).
    assert run_case(
        case, _runner("Yes, a prior catheterization was performed in 2023.", {"tool_calls": 1, "tool_failures": 0})
    ).passed is False
