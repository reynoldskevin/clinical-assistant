"""T21 acceptance tests (LOCKED) for the UC-8 eval case (tool chaining + budget).

Proves the chaining case loads through the harness with a tool-use requirement and
a max-tool-calls budget grader, and that the budget grader enforces the cap. Graded
offline against an injected runner; no live API call.
"""
import os

from eval import load_cases, run_case

UC8_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc8.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC8_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def _chain_case():
    return next(c for c in _cases() if "chain" in c.name.lower() or "encounter" in c.name.lower())


def test_uc8_case_loads_with_tool_use_and_budget_graders():
    assert len(_cases()) >= 1
    c = _chain_case()
    assert any("tool_used" in g and g["tool_used"] is True for g in c.graders)
    assert any("max_tool_calls" in g for g in c.graders)


def test_uc8_budget_grader_enforces_the_cap():
    c = _chain_case()
    cap = next(g["max_tool_calls"] for g in c.graders if "max_tool_calls" in g)
    term = _contains_any(c)[0]

    # A grounded, chained answer within the tool-call budget -> pass.
    assert run_case(c, _runner(f"After looking it up, {term}.", {"tool_calls": cap, "tool_failures": 0})).passed is True
    # Exceeding the budget -> fail (the cap is enforced).
    assert run_case(c, _runner(f"After looking it up, {term}.", {"tool_calls": cap + 1, "tool_failures": 0})).passed is False
    # Never consulted a tool -> fail.
    assert run_case(c, _runner(f"{term}.", {"tool_calls": 0, "tool_failures": 0})).passed is False
