"""T59b acceptance tests (LOCKED) — Week-2 alert logic.

On top of T59a's panel aggregation, the Week-2 alerts (W2_ARCHITECTURE.md §7/§10)
add the DERIVABLE alert decisions:

  * an extraction-failure-rate alert — fires when the non-`ok` `extraction.field`
    rate over a window exceeds a threshold (with a volume floor to avoid noise);
  * a per-CATEGORY eval-regression detector — fires when any eval category's pass
    rate drops by MORE than 5% below a baseline (mirrors `ci_gate.MAX_REGRESSION`:
    a drop of EXACTLY 5% is allowed), consuming T59a's `by_category` shape.

Deterministic: pure functions over in-memory metrics; the regression contract test
feeds real `eval.run_all` `by_category` summaries. No network.
"""
import textwrap

import pytest

from alerts import detect_eval_regression, evaluate_extraction_failure
from eval import run_all
from events import EXTRACTION_FIELD, log_event
from panels import aggregate_week2_events


def _panel_with(ok, unsupported=0, low_conf=0):
    cid = "c"
    events = (
        [log_event(EXTRACTION_FIELD, cid, field=f"ok{i}", outcome="ok") for i in range(ok)]
        + [log_event(EXTRACTION_FIELD, cid, field=f"u{i}", outcome="unsupported") for i in range(unsupported)]
        + [log_event(EXTRACTION_FIELD, cid, field=f"l{i}", outcome="low_confidence") for i in range(low_conf)]
    )
    return aggregate_week2_events(events)


# --- extraction-failure-rate alert --------------------------------------------

def test_extraction_alert_fires_above_threshold():
    # 6 ok + 4 failed of 10 -> 0.4 failure rate > 0.2 threshold
    panel = _panel_with(ok=6, unsupported=3, low_conf=1)
    result = evaluate_extraction_failure(panel, threshold=0.2, min_fields=5)
    assert result["firing"] is True
    assert result["rate"] == pytest.approx(0.4)


def test_extraction_alert_does_not_fire_at_or_below_threshold():
    # exactly 0.2 failure rate is NOT > 0.2 -> not firing
    panel = _panel_with(ok=8, unsupported=2)
    result = evaluate_extraction_failure(panel, threshold=0.2, min_fields=5)
    assert result["firing"] is False
    assert result["rate"] == pytest.approx(0.2)


def test_extraction_alert_respects_volume_floor():
    # 100% failure but only 3 observations (< min_fields=5) -> suppressed
    panel = _panel_with(ok=0, unsupported=3)
    result = evaluate_extraction_failure(panel, threshold=0.2, min_fields=5)
    assert result["firing"] is False


def test_extraction_alert_empty_is_not_firing():
    result = evaluate_extraction_failure(_panel_with(ok=0), threshold=0.2, min_fields=5)
    assert result["firing"] is False
    assert result["rate"] == 0.0


# --- per-category eval-regression detector ------------------------------------

def _bc(**cats):
    """Build a by_category mapping {cat: {passed,total,pass_rate}} from pass rates."""
    return {c: {"passed": int(r * 10), "total": 10, "pass_rate": r} for c, r in cats.items()}


def test_regression_at_exactly_five_percent_is_allowed():
    baseline = _bc(diabetes=1.0)
    current = _bc(diabetes=0.95)   # drop of exactly 0.05 -> allowed
    assert detect_eval_regression(baseline, current) == []


def test_regression_greater_than_five_percent_fires():
    baseline = _bc(diabetes=1.0)
    current = _bc(diabetes=0.94)   # drop of 0.06 > 0.05 -> regression
    assert detect_eval_regression(baseline, current) == ["diabetes"]


def test_missing_current_category_is_a_full_drop():
    baseline = _bc(diabetes=1.0, hypertension=1.0)
    current = _bc(diabetes=1.0)    # hypertension absent -> full drop -> regression
    assert detect_eval_regression(baseline, current) == ["hypertension"]


def test_category_absent_from_baseline_is_ignored():
    baseline = _bc(diabetes=1.0)
    current = _bc(diabetes=1.0, newcat=0.0)   # newcat has no baseline -> ignored
    assert detect_eval_regression(baseline, current) == []


def test_multiple_regressions_returned_sorted():
    baseline = _bc(alpha=1.0, beta=1.0, gamma=1.0)
    current = _bc(alpha=0.5, beta=1.0, gamma=0.2)
    assert detect_eval_regression(baseline, current) == ["alpha", "gamma"]


def test_regression_consumes_real_run_all_by_category(tmp_path):
    # Contract (decision #12): feed the REAL by_category shape from run_all, not a
    # hand-rolled fake — the same producer T59a's panel reads.
    yaml_text = textwrap.dedent(
        """
        - {name: d1, question: q, pid: 1, category: diabetes, graders: [{contains: "yes"}]}
        - {name: d2, question: q, pid: 1, category: diabetes, graders: [{contains: "yes"}]}
        """
    ).strip()
    d = tmp_path / "evals"
    d.mkdir()
    (d / "c.yaml").write_text(yaml_text)

    baseline = run_all(str(d), lambda q, pid: ("yes", {"tool_calls": 0}))    # both pass -> 1.0
    current = run_all(str(d), lambda q, pid: ("no", {"tool_calls": 0}))      # both fail -> 0.0
    assert detect_eval_regression(baseline["by_category"], current["by_category"]) == ["diabetes"]
