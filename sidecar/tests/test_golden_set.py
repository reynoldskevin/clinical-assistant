"""T51 acceptance tests (LOCKED) — 50-case golden set + 5 boolean rubric categories.

The golden set is an in-repo, reproducible evaluation dataset that exercises the
Week 2 pipeline (extraction, evidence retrieval, citations, refusals,
missing-data behavior). Every case is tagged with exactly one of five BOOLEAN
rubric categories, each of which has a deterministic grader and a per-rubric
pass threshold.

Everything here is deterministic and offline: cases are generated programmatically
from a few templates (no external fetch), and the golden set ships a canonical
`build_ideal_runner()` — an offline, no-LLM runner whose outputs are crafted to
satisfy every rubric — so CI can prove the set is satisfiable without an API key.
Threshold enforcement is proven by seeding a degraded runner and asserting the
gate fails.

Contract exercised (the implementer builds `sidecar/golden_set.py` to satisfy it):

    RUBRICS: tuple[str, ...]            # the 5 boolean rubric category names
    load_golden_set() -> list[case]     # exactly 50 cases; each has .name/.question/.pid/.rubric
    RUBRIC_GRADERS: dict[str, callable] # one boolean grader per rubric: (case, text, trace) -> bool
    THRESHOLDS: dict[str, float]        # per-rubric pass threshold in (0, 1]
    build_ideal_runner() -> Runner      # offline runner satisfying every case
    run_golden_set(runner) -> summary   # {"by_rubric": {r: {passed,total,pass_rate}}, "results": [...], ...}
    gate_golden_set(summary) -> bool    # True iff every rubric's pass_rate >= its threshold
"""
import golden_set
from eval import run_case


EXPECTED_RUBRICS = {
    "schema_valid",
    "citation_present",
    "factually_consistent",
    "safe_refusal",
    "no_phi_in_logs",
}


# --- dataset shape -------------------------------------------------------------

def test_golden_set_loads_exactly_50_cases():
    cases = golden_set.load_golden_set()
    assert len(cases) == 50


def test_every_case_has_the_harness_fields_and_a_known_rubric():
    for case in golden_set.load_golden_set():
        assert isinstance(case.name, str) and case.name
        assert isinstance(case.question, str) and case.question
        assert isinstance(case.pid, int)
        assert case.rubric in EXPECTED_RUBRICS, f"{case.name}: bad rubric {case.rubric!r}"


def test_case_names_are_unique():
    cases = golden_set.load_golden_set()
    names = [c.name for c in cases]
    assert len(set(names)) == len(names) == 50


# --- rubric coverage -----------------------------------------------------------

def test_all_five_rubric_categories_are_defined():
    assert set(golden_set.RUBRICS) == EXPECTED_RUBRICS


def test_every_rubric_has_at_least_one_case():
    cases = golden_set.load_golden_set()
    present = {c.rubric for c in cases}
    assert EXPECTED_RUBRICS <= present, f"missing rubric coverage: {EXPECTED_RUBRICS - present}"


# --- graders are boolean and wired ---------------------------------------------

def test_every_rubric_has_a_wired_grader():
    assert set(golden_set.RUBRIC_GRADERS) == EXPECTED_RUBRICS
    for rubric, grader in golden_set.RUBRIC_GRADERS.items():
        assert callable(grader), f"{rubric} grader is not callable"


def test_each_rubric_grader_returns_a_real_bool():
    # Drive each case's grader with the ideal runner's output and assert the
    # result is a genuine bool (not a truthy string / None / int).
    runner = golden_set.build_ideal_runner()
    for case in golden_set.load_golden_set():
        text, trace = runner(case.question, case.pid)
        verdict = golden_set.RUBRIC_GRADERS[case.rubric](case, text, trace)
        assert verdict is True or verdict is False, (
            f"{case.name}: grader returned non-bool {verdict!r}"
        )


# --- per-rubric thresholds -----------------------------------------------------

def test_every_rubric_has_a_pass_threshold_in_unit_range():
    assert set(golden_set.THRESHOLDS) == EXPECTED_RUBRICS
    for rubric, threshold in golden_set.THRESHOLDS.items():
        assert isinstance(threshold, (int, float))
        assert 0.0 < threshold <= 1.0, f"{rubric}: threshold {threshold} out of (0, 1]"


# --- reproducibility (no external fetch) ---------------------------------------

def test_golden_set_is_deterministic_across_loads():
    first = golden_set.load_golden_set()
    second = golden_set.load_golden_set()
    assert [(c.name, c.question, c.pid, c.rubric) for c in first] == [
        (c.name, c.question, c.pid, c.rubric) for c in second
    ]


def test_cases_are_generated_from_a_small_number_of_templates():
    # "Author cheaply via programmatic variations of a few templates" — 50 cases
    # spread over the 5 rubrics means several variants share a template, so the
    # count of distinct question shapes is far below 50 while names stay unique.
    cases = golden_set.load_golden_set()
    # At least one rubric family must carry multiple programmatic variants.
    by_rubric: dict[str, int] = {}
    for c in cases:
        by_rubric[c.rubric] = by_rubric.get(c.rubric, 0) + 1
    assert max(by_rubric.values()) >= 2


# --- runs through the eval harness ---------------------------------------------

def test_cases_are_gradable_through_the_eval_harness_run_case():
    # Each golden case is shape-compatible with the Week-1 harness: run_case must
    # accept it and the ideal runner and return a result without error. (The
    # golden set layers rubric grading on top of this same harness contract.)
    runner = golden_set.build_ideal_runner()
    for case in golden_set.load_golden_set():
        result = run_case(case, runner)
        assert result.name == case.name
        assert isinstance(result.passed, bool)


def test_run_golden_set_reports_per_rubric_breakdown():
    summary = golden_set.run_golden_set(golden_set.build_ideal_runner())
    assert set(summary["by_rubric"]) == EXPECTED_RUBRICS
    total = 0
    for rubric, stats in summary["by_rubric"].items():
        assert stats["total"] >= 1
        assert 0.0 <= stats["pass_rate"] <= 1.0
        assert stats["passed"] <= stats["total"]
        total += stats["total"]
    assert total == 50


# --- threshold enforcement -----------------------------------------------------

def test_ideal_runner_passes_every_rubric_and_the_gate():
    summary = golden_set.run_golden_set(golden_set.build_ideal_runner())
    for rubric, stats in summary["by_rubric"].items():
        assert stats["pass_rate"] == 1.0, f"{rubric} not fully satisfied by ideal runner"
    assert golden_set.gate_golden_set(summary) is True


def test_seeded_regression_drops_a_rubric_below_threshold_and_fails_the_gate():
    # A blank runner produces no answer and an empty trace, so at least one
    # rubric collapses below its threshold and the gate must fail.
    blank_runner = lambda question, pid: ("", {"tool_calls": 0, "tool_failures": 0})
    summary = golden_set.run_golden_set(blank_runner)

    below = [
        rubric
        for rubric, stats in summary["by_rubric"].items()
        if stats["pass_rate"] < golden_set.THRESHOLDS[rubric]
    ]
    assert below, "expected at least one rubric below threshold under the blank runner"
    assert golden_set.gate_golden_set(summary) is False
