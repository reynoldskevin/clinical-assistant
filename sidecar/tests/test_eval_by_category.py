"""T59a acceptance tests (LOCKED) — per-category eval breakdown.

The eval pass/fail-per-category panel needs a per-category breakdown that does not
exist yet: `EvalResult` carries no category and `run_all` only aggregates overall
pass/total. This ticket adds `category` to `EvalResult` and a `by_category`
breakdown to the `run_all` summary (additive, backward-compatible), and exposes it
via `panels.eval_pass_fail_by_category`.

Deterministic: a tiny temp evals dir + a fixed offline runner; no network.
"""
import textwrap

import eval as evalmod
from eval import EvalCase, run_all, run_case
from panels import eval_pass_fail_by_category


def _runner(question, pid):
    """Deterministic runner: output contains 'yes'; no tool calls."""
    return "yes ok", {"tool_calls": 0}


# A case passes iff its grader matches "yes"; fails on "zzz". Categories assigned
# so we can assert the per-category rollup independently of pass/fail.
def _write_cases(tmp_path):
    yaml_text = textwrap.dedent(
        """
        - name: dia_pass
          question: q1
          pid: 1
          category: diabetes
          graders: [{contains: "yes"}]
        - name: dia_fail
          question: q2
          pid: 1
          category: diabetes
          graders: [{contains: "zzz"}]
        - name: htn_pass
          question: q3
          pid: 1
          category: hypertension
          graders: [{contains: "yes"}]
        - name: uncat_pass
          question: q4
          pid: 1
          graders: [{contains: "yes"}]
        """
    ).strip()
    d = tmp_path / "evals"
    d.mkdir()
    (d / "cases.yaml").write_text(yaml_text)
    return str(d)


def test_eval_result_carries_category():
    case = EvalCase(name="c", question="q", pid=1, graders=[{"contains": "yes"}], category="diabetes")
    result = run_case(case, _runner)
    assert result.category == "diabetes"
    assert result.passed is True


def test_eval_result_category_defaults_to_none():
    case = EvalCase(name="c", question="q", pid=1, graders=[{"contains": "yes"}])
    assert run_case(case, _runner).category is None


def test_run_all_summary_has_by_category_breakdown(tmp_path):
    summary = run_all(_write_cases(tmp_path), _runner)
    bc = summary["by_category"]
    assert bc["diabetes"] == {"passed": 1, "total": 2, "pass_rate": 0.5}
    assert bc["hypertension"] == {"passed": 1, "total": 1, "pass_rate": 1.0}
    # a case with no category is grouped under a stable "uncategorized" key
    assert bc["uncategorized"] == {"passed": 1, "total": 1, "pass_rate": 1.0}


def test_existing_summary_keys_unchanged(tmp_path):
    summary = run_all(_write_cases(tmp_path), _runner)
    # additive only — the Week-1 keys and overall totals still hold
    assert summary["total"] == 4
    assert summary["passed"] == 3
    for key in ("passed", "total", "pass_rate", "by_file", "results", "categories"):
        assert key in summary


def test_panels_eval_pass_fail_by_category_reflects_summary(tmp_path):
    summary = run_all(_write_cases(tmp_path), _runner)
    view = eval_pass_fail_by_category(summary)
    assert view["diabetes"]["passed"] == 1
    assert view["diabetes"]["total"] == 2
    assert view["hypertension"]["pass_rate"] == 1.0
