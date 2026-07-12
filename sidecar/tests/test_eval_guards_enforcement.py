"""T34 acceptance tests (LOCKED) — every eval case guards a documented failure mode.

Engineering deliverable: every evaluation case must exercise a boundary condition,
an invariant, or a known regression risk, and document the failure mode it guards
against; happy-path-only suites do not pass. This is enforced here: every packaged
eval case must declare a `guards: {type, failure_mode}` block with a valid type and
a non-empty failure_mode, and the suite as a whole must cover all three types.
Deterministic — inspects the packaged eval YAML only, no runner, no live API.
"""
import glob
import os

from eval import load_cases

EVALS_DIR = os.path.join(os.path.dirname(__file__), "..", "evals")
ALLOWED_TYPES = {"boundary", "invariant", "regression"}


def _all_cases():
    cases = []
    for path in sorted(glob.glob(os.path.join(EVALS_DIR, "*.yaml"))):
        with open(path) as fh:
            cases.extend((os.path.basename(path), c) for c in load_cases(fh.read()))
    return cases


def _valid_guard(guards) -> bool:
    """The rule: a valid guard is a mapping with an allowed type and non-empty text."""
    return (
        isinstance(guards, dict)
        and guards.get("type") in ALLOWED_TYPES
        and isinstance(guards.get("failure_mode"), str)
        and guards["failure_mode"].strip() != ""
    )


def test_packaged_evals_are_present():
    # Sanity: the packaged suite is non-trivial (guards against an empty glob).
    cases = _all_cases()
    assert len(cases) >= 15


def test_every_packaged_case_declares_a_valid_guard():
    offenders = [
        f"{fname}:{case.name} -> {getattr(case, 'guards', None)!r}"
        for fname, case in _all_cases()
        if not _valid_guard(getattr(case, "guards", None))
    ]
    assert offenders == [], (
        "Every eval case must declare guards {type in "
        f"{sorted(ALLOWED_TYPES)}, non-empty failure_mode}}. Offenders: {offenders}"
    )


def test_suite_covers_all_three_guard_types():
    types = {
        case.guards["type"]
        for _, case in _all_cases()
        if _valid_guard(getattr(case, "guards", None))
    }
    assert ALLOWED_TYPES <= types, f"missing guard types: {ALLOWED_TYPES - types}"


def test_failure_modes_are_documented_not_placeholders():
    # Each failure_mode must be a real sentence, not a stub.
    thin = [
        f"{fname}:{case.name}"
        for fname, case in _all_cases()
        if _valid_guard(getattr(case, "guards", None))
        and len(case.guards["failure_mode"].strip()) < 15
    ]
    assert thin == [], f"failure_mode too short to document a real risk: {thin}"


def test_rule_helper_rejects_missing_or_invalid_guards():
    # The enforcement helper itself must reject the bad shapes it is meant to catch.
    assert _valid_guard(None) is False
    assert _valid_guard({}) is False
    assert _valid_guard({"type": "happy", "failure_mode": "x"}) is False
    assert _valid_guard({"type": "boundary", "failure_mode": ""}) is False
    assert _valid_guard({"type": "boundary"}) is False
    assert _valid_guard({"type": "invariant", "failure_mode": "answers from memory not the chart"}) is True
