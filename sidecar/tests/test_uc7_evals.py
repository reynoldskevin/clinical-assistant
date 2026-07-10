"""T20 acceptance tests (LOCKED) for the UC-7 eval case (search_chart).

Proves the chart-search case loads through the harness and that its graders demand
real boundary tool use plus grounded content from the notes. Graded offline against
an injected runner; no live API call.
"""
import os

from eval import load_cases, run_case

UC7_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc7.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC7_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def test_uc7_case_loads_and_targets_search():
    cases = _cases()
    assert len(cases) >= 1
    case = next(c for c in cases if "search" in c.name.lower() or "note" in c.name.lower())
    q = case.question.lower()
    assert "search" in q or "note" in q or "mention" in q


def test_uc7_search_case_requires_tool_use_and_grounded_content():
    case = next(c for c in _cases() if "search" in c.name.lower() or "note" in c.name.lower())
    assert any("tool_used" in g and g["tool_used"] is True for g in case.graders)

    term = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    # Ran the search and reports what the notes contain -> pass.
    assert run_case(case, _runner(f"The notes mention {term}.", good)).passed is True
    # Same content but never searched -> fail.
    assert run_case(case, _runner(f"The notes mention {term}.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # Searched but produced no content -> fail.
    assert run_case(case, _runner("", good)).passed is False
