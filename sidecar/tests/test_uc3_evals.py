"""T26 acceptance tests (LOCKED) for the UC-3 eval cases (contemplated-action context).

UC-3 (USER.md): before a contemplated action (contrast / ketorolac / a sedative) the
agent SURFACES the patient-specific context that bears on the decision (relevant
allergies, current meds, recent renal function, prior reactions) but DEFERS the hard
dose/interaction verdict to deterministic tools — it points at the check, it does not
perform it. So a passing answer names patient-specific context AND withholds a
definitive verdict/dose; emitting the verdict fails. Graded offline against an
injected runner; expected substrings read from the loaded case.
"""
import os

from eval import load_cases, run_case

UC3_YAML = os.path.join(os.path.dirname(__file__), "..", "evals", "uc3.yaml")


def _runner(text, trace):
    return lambda question, pid: (text, trace)


def _cases():
    with open(UC3_YAML) as fh:
        return load_cases(fh.read())


def _defer_case():
    # The UC-3 deferral case surfaces context (contains_any) yet must exclude a
    # definitive dose/interaction verdict (excludes).
    return next(
        c for c in _cases()
        if c.uc == 3
        and any("contains_any" in g for g in c.graders)
        and any("excludes" in g for g in c.graders)
    )


def _contains_any(case):
    return next(g["contains_any"] for g in case.graders if "contains_any" in g)


def _excludes(case):
    return next(g["excludes"] for g in case.graders if "excludes" in g)


def test_uc3_case_loads_and_is_tagged_deferral():
    case = _defer_case()
    assert case.uc == 3
    assert case.category == "deferral"


def test_surfacing_context_while_withholding_the_verdict_passes():
    case = _defer_case()
    context_term = _contains_any(case)[0]
    trace = {"tool_calls": 1, "tool_failures": 0}
    # Names patient-specific context, points at (but does not perform) the hard check.
    text = f"Relevant context from the chart: {context_term}. Please confirm with the interaction checker."
    assert run_case(case, _runner(text, trace)).passed is True


def test_emitting_a_definitive_verdict_fails():
    case = _defer_case()
    context_term = _contains_any(case)[0]
    verdict = str(_excludes(case))
    trace = {"tool_calls": 1, "tool_failures": 0}
    # Surfaces context BUT also emits the forbidden definitive verdict/dose -> fail.
    text = f"Context: {context_term}. {verdict}"
    assert run_case(case, _runner(text, trace)).passed is False


def test_no_tool_use_fails():
    case = _defer_case()
    context_term = _contains_any(case)[0]
    assert run_case(
        case, _runner(f"{context_term}.", {"tool_calls": 0, "tool_failures": 0})
    ).passed is False
