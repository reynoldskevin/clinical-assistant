"""T17 acceptance tests (LOCKED) for the UC-4 eval case (encounter history).

Proves the encounter-history case loads through the harness and that its graders
demand real boundary tool use plus encounter content, rewarding a grounded answer
over a hollow one. Graded offline against an injected runner — no live API call.
Expected substrings are read from the loaded case so the test isn't coupled to
exact wording.
"""
import os

from eval import load_cases, run_case

UC4_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc4.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC4_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def test_uc4_case_loads_and_targets_encounters():
    cases = _cases()
    assert len(cases) >= 1
    encounter_case = next(c for c in cases if "encounter" in c.name.lower())
    # The question is about the patient's visit/encounter history.
    assert "encounter" in encounter_case.question.lower() or "visit" in encounter_case.question.lower()


def test_uc4_encounter_case_requires_tool_use_and_encounter_content():
    case = next(c for c in _cases() if "encounter" in c.name.lower())
    # It must be graded on genuine boundary use.
    assert any("tool_used" in g and g["tool_used"] is True for g in case.graders)

    term = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    # Grounded answer that used the boundary and names encounter content -> pass.
    assert run_case(case, _runner(f"The patient has several visits, including one for {term}.", good)).passed is True
    # Same content but the boundary was never consulted -> fail.
    assert run_case(case, _runner(f"The patient has visits for {term}.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # Used the tool but produced no encounter content -> fail.
    assert run_case(case, _runner("", good)).passed is False
