"""T27 acceptance tests (LOCKED) for the data-quality eval case (free-text-only flag).

USER.md §6: uncoded / free-text-only problems & meds are common — the agent must
read the narrative and SAY when a problem/med is documented only as free text
(i.e. has no diagnosis / rxnorm code). This is the one genuinely-new data-quality
signal for T27; gap/absence and stale-active honesty are already covered by the
verification gate and earlier evals. Graded offline against an injected runner;
expected substrings read from the loaded case.
"""
import os

from eval import load_cases, run_case

DQ_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc_data_quality.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(DQ_YAML) as fh:
        return load_cases(fh.read())


def _free_text_case():
    return next(c for c in _cases() if c.name == "dq_free_text_only_flagged")


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def test_case_loads_and_is_tagged_data_quality():
    case = _free_text_case()
    assert case.category == "data_quality"


def test_flagging_free_text_status_from_the_chart_passes():
    case = _free_text_case()
    flag_phrase = _contains_any(case)[0]
    good = {"tool_calls": 1, "tool_failures": 0}
    text = f"That problem is documented as {flag_phrase} — there is no diagnosis code on it."
    assert run_case(case, _runner(text, good)).passed is True


def test_not_flagging_the_uncoded_status_fails():
    case = _free_text_case()
    good = {"tool_calls": 1, "tool_failures": 0}
    # Read the chart but answered as if it were a normal coded diagnosis -> fail.
    assert run_case(case, _runner("Yes, that is an active diagnosis.", good)).passed is False


def test_answering_without_reading_the_chart_fails():
    case = _free_text_case()
    flag_phrase = _contains_any(case)[0]
    assert run_case(
        case, _runner(f"It is {flag_phrase}.", {"tool_calls": 0, "tool_failures": 0})
    ).passed is False
