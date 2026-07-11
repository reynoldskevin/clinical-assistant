"""T26 acceptance tests (LOCKED) for the UC-2 eval cases (focused clinical Q&A).

UC-2 (USER.md): a specific, ad-hoc factual question answered grounded strictly in
this patient's record. The happy case demands tool use + grounded clinical content;
the missing-fact case rewards an honest "not documented" over a fabricated specific
value. Expected substrings are read from the loaded case, so the tests are not
coupled to exact wording. Graded offline against an injected runner.
"""
import os

from eval import load_cases, run_case

UC2_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc2.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC2_YAML) as fh:
        return load_cases(fh.read())


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def test_uc2_cases_load_and_are_tagged():
    cases = _cases()
    assert len(cases) >= 2
    # UC-2 cases declare their use case so the coverage sweep can see them.
    assert any(c.uc == 2 for c in cases)


def test_focused_qa_requires_tool_use_and_grounded_content():
    case = next(c for c in _cases() if c.uc == 2 and any("tool_used" in g for g in c.graders))
    term = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}

    assert run_case(case, _runner(f"On reviewing the chart: {term}.", good)).passed is True
    # answered without reading the chart -> fail
    assert run_case(case, _runner(f"{term}.", {"tool_calls": 0, "tool_failures": 0})).passed is False
    # used the tool but produced no grounded content -> fail
    assert run_case(case, _runner("", good)).passed is False


def test_missing_specific_fact_rewards_honesty_penalizes_fabrication():
    # A UC-2 case whose graders reward an honest hedge (contains_any of honesty
    # phrasing) is the missing-fact case.
    honest_case = next(
        c for c in _cases()
        if c.uc == 2 and not any("tool_used" in g for g in c.graders)
        and any("contains_any" in g for g in c.graders)
    )
    honest_phrase = _contains_any(honest_case)[0]
    trace = {"tool_calls": 1, "tool_failures": 0}

    assert run_case(honest_case, _runner(f"That is {honest_phrase}.", trace)).passed is True
    # a fabricated specific value with no honest hedge -> fail
    assert run_case(honest_case, _runner("The value is 7.2.", trace)).passed is False
