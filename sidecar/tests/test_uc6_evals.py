"""T19 acceptance tests (LOCKED) for the UC-6 eval case (stale-active medication).

Proves the medications case loads through the harness and that its graders demand
real boundary tool use AND a staleness hedge — rewarding an answer that surfaces
the stale-active conflict over one that flatly asserts the med is current. Graded
offline against an injected runner; no live API call.
"""
import os

from eval import load_cases, run_case

UC6_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc6.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC6_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def test_uc6_case_loads_and_targets_medications():
    cases = _cases()
    assert len(cases) >= 1
    med_case = next(c for c in cases if "medication" in c.name.lower() or "stale" in c.name.lower())
    q = med_case.question.lower()
    assert "taking" in q or "medication" in q or "warfarin" in q


def test_uc6_stale_active_case_requires_tool_use_and_a_staleness_hedge():
    case = next(c for c in _cases() if "medication" in c.name.lower() or "stale" in c.name.lower())
    assert any("tool_used" in g and g["tool_used"] is True for g in case.graders)

    term = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    # Consulted the record AND hedges on staleness -> pass.
    assert run_case(case, _runner(f"The record lists it as active, but its {term} suggests it may be stale.", good)).passed is True
    # Same hedge but never consulted the boundary -> fail.
    assert run_case(case, _runner(f"Its {term} suggests it may be stale.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # Flatly asserts it's current, no staleness hedge -> fail.
    assert run_case(case, _runner("Yes, the patient is currently taking it.", good)).passed is False
