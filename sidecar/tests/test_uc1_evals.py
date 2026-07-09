"""T15 acceptance tests (LOCKED) for the UC-1 eval cases.

Proves the happy-path case demands tool use + clinical content, and the missing-data
case rewards an honest "not documented" answer over a fabricated value. Expected
substrings are read from the loaded case so the test isn't coupled to exact wording.
"""
import os

from eval import load_cases, run_case

UC1_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc1.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC1_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def test_uc1_cases_load():
    names = {c.name for c in _cases()}
    assert "uc1_happy_summary" in names
    assert "uc1_missing_data_no_fabrication" in names


def test_happy_case_requires_tool_use_and_clinical_content():
    case = next(c for c in _cases() if c.name == "uc1_happy_summary")
    term = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    assert run_case(case, _runner(f"Summary: {term} noted.", good)).passed is True
    # didn't use the boundary -> fail
    assert run_case(case, _runner(f"Summary: {term} noted.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # used the tool but produced no clinical content -> fail
    assert run_case(case, _runner("", good)).passed is False


def test_missing_data_case_rewards_honesty_penalizes_fabrication():
    case = next(c for c in _cases() if c.name == "uc1_missing_data_no_fabrication")
    honest_phrase = _contains_any(case)[0]
    trace = {"tool_calls": 1, "tool_failures": 0}

    assert run_case(case, _runner(f"That result is {honest_phrase}.", trace)).passed is True
    # a fabricated specific value with no honest hedge -> fail
    assert run_case(case, _runner("The HbA1c is 7.2 percent.", trace)).passed is False
