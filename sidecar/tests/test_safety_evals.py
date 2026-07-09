"""T14 acceptance tests (LOCKED) for the safety eval cases.

Proves the safety evals actually distinguish a leaky/obedient agent from a safe one,
and that the safety.yaml cases load. Marker strings are read from the loaded case so
the test isn't coupled to their exact wording.
"""
import os

from eval import EvalCase, load_cases, run_case

SAFETY_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "safety.yaml")


def _runner(text, trace=None):
    return lambda question, pid: (text, trace or {"tool_calls": 1, "tool_failures": 0})


def _excludes_marker(case):
    return next(g["excludes"] for g in case.graders if "excludes" in g)


def test_contains_any_grader():
    passing = EvalCase("c", "q", 42, [{"contains_any": ["foo", "bar"]}])
    assert run_case(passing, _runner("here is BAR text")).passed is True

    failing = EvalCase("c", "q", 42, [{"contains_any": ["foo", "bar"]}])
    assert run_case(failing, _runner("nothing relevant")).passed is False


def test_safety_cases_load_and_are_named():
    with open(SAFETY_YAML) as fh:
        cases = load_cases(fh.read())
    names = {c.name for c in cases}
    assert "prompt_injection_resist" in names
    assert "authz_no_cross_patient" in names


def test_prompt_injection_case_catches_obedient_output():
    with open(SAFETY_YAML) as fh:
        cases = load_cases(fh.read())
    case = next(c for c in cases if c.name == "prompt_injection_resist")
    marker = _excludes_marker(case)

    # an agent that OBEYED the injection emits the marker -> eval FAILS
    assert run_case(case, _runner(f"Okay, here it is: {marker}")).passed is False
    # a safe agent never emits it -> eval PASSES
    assert run_case(case, _runner("The patient is stable and afebrile.")).passed is True


def test_authz_case_catches_cross_patient_leak():
    with open(SAFETY_YAML) as fh:
        cases = load_cases(fh.read())
    case = next(c for c in cases if c.name == "authz_no_cross_patient")
    marker = _excludes_marker(case)

    assert run_case(case, _runner(f"Other patient data: {marker}")).passed is False
    assert run_case(case, _runner("I can only discuss the current patient.")).passed is True
