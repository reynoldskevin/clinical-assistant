"""T52 — PR-blocking per-rubric regression gate over the T51 golden set.

Extends the Week-1/Week-2 eval gate with a *regression* check: a rubric fails
the gate if its pass rate either drops by MORE than :data:`MAX_REGRESSION`
below a reproducible baseline, OR falls below its own per-rubric threshold.

Everything here is pure, deterministic, and offline — no Claude, no VLM, no
network, no I/O, no randomness. The baseline is derived from the golden set's
canonical ideal runner (:func:`golden_set.build_ideal_runner`), so it is
reproducible from source and covers every rubric at 1.0.
"""
from __future__ import annotations

from golden_set import (
    RUBRICS,
    THRESHOLDS,
    build_ideal_runner,
    run_golden_set,
)

#: A pass-rate drop STRICTLY greater than this (5%) below baseline is a
#: regression. A drop of exactly this amount is allowed.
MAX_REGRESSION: float = 0.05


def pass_rates(summary: dict) -> dict[str, float]:
    """Extract ``{rubric: pass_rate}`` from a :func:`run_golden_set` summary.

    Covers every rubric in :data:`golden_set.RUBRICS`, pulling
    ``summary["by_rubric"][rubric]["pass_rate"]``.
    """
    by_rubric = summary["by_rubric"]
    return {rubric: float(by_rubric[rubric]["pass_rate"]) for rubric in RUBRICS}


def baseline_pass_rates() -> dict[str, float]:
    """Return the reproducible, offline per-rubric baseline pass rates.

    Derived deterministically from the golden set's ideal runner, so every
    rubric baselines at 1.0. No network, no I/O, no randomness — repeated calls
    return equal dicts.
    """
    return pass_rates(run_golden_set(build_ideal_runner()))


def regression_gate(
    current: dict[str, float],
    baseline: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    max_regression: float = MAX_REGRESSION,
) -> dict:
    """Grade ``current`` per-rubric pass rates against baseline and thresholds.

    A rubric REGRESSES iff ``baseline - current > max_regression`` (a drop of
    exactly ``max_regression`` is allowed). A rubric is BELOW_THRESHOLD iff
    ``current < thresholds[rubric]``. The gate passes iff there are neither
    regressions nor below-threshold rubrics.

    Returns a dict with keys ``passed`` (a genuine :class:`bool`),
    ``regressions``, ``below_threshold`` (both lists of rubric names in
    :data:`RUBRICS` order), and ``by_rubric`` (per-rubric detail for
    observability). Missing ``current`` rates are treated as ``0.0``.
    """
    if baseline is None:
        baseline = baseline_pass_rates()
    if thresholds is None:
        thresholds = THRESHOLDS

    rubrics = list(RUBRICS) + [r for r in baseline if r not in RUBRICS]

    regressions: list[str] = []
    below_threshold: list[str] = []
    by_rubric: dict[str, dict] = {}

    for rubric in rubrics:
        current_rate = float(current.get(rubric, 0.0))
        baseline_rate = float(baseline.get(rubric, 0.0))
        threshold = float(thresholds.get(rubric, 0.0))
        drop = baseline_rate - current_rate

        # Strictly-greater comparison with a small epsilon so a drop of exactly
        # ``max_regression`` (which floating-point may render as e.g.
        # 0.050000000000000044) is treated as allowed, not a regression.
        is_regression = drop > max_regression + 1e-9
        is_below_threshold = current_rate < threshold

        if is_regression:
            regressions.append(rubric)
        if is_below_threshold:
            below_threshold.append(rubric)

        by_rubric[rubric] = {
            "current": current_rate,
            "baseline": baseline_rate,
            "drop": drop,
            "threshold": threshold,
            "regression": is_regression,
            "below_threshold": is_below_threshold,
        }

    passed = not regressions and not below_threshold

    return {
        "passed": bool(passed),
        "regressions": regressions,
        "below_threshold": below_threshold,
        "by_rubric": by_rubric,
    }
