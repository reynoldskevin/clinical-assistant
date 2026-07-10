"""T18 acceptance tests (LOCKED) for the UC-5 eval case (lab/diagnostic results).

Proves the results case loads through the harness and that its graders demand real
boundary tool use plus results content, rewarding a grounded answer over a hollow
one. Graded offline against an injected runner — no live API call. Expected
substrings are read from the loaded case so the test isn't coupled to exact wording.
"""
import os

from eval import load_cases, run_case

UC5_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc5.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC5_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def test_uc5_case_loads_and_targets_results():
    cases = _cases()
    assert len(cases) >= 1
    results_case = next(c for c in cases if "result" in c.name.lower() or "lab" in c.name.lower())
    q = results_case.question.lower()
    assert "result" in q or "lab" in q


def test_uc5_results_case_requires_tool_use_and_results_content():
    case = next(c for c in _cases() if "result" in c.name.lower() or "lab" in c.name.lower())
    assert any("tool_used" in g and g["tool_used"] is True for g in case.graders)

    term = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    # Grounded answer that used the boundary and names a result -> pass.
    assert run_case(case, _runner(f"The most recent lab shows {term}.", good)).passed is True
    # Same content but the boundary was never consulted -> fail.
    assert run_case(case, _runner(f"The lab shows {term}.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # Used the tool but produced no results content -> fail.
    assert run_case(case, _runner("", good)).passed is False
