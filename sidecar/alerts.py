"""Week-2 derivable alert logic.

The Week-2 alerts (``W2_ARCHITECTURE.md`` §7/§10, documented with runbooks in
``ALERTS.md``) that can be decided from the T57 structured events / eval
summaries — as opposed to the Braintrust UI-configured alerts — live here:

  * :func:`evaluate_extraction_failure` — an extraction-failure-rate alert over
    the ``extraction.field`` outcomes surfaced by :func:`panels.aggregate_week2_events`;
  * :func:`detect_eval_regression` — a per-CATEGORY eval-regression detector over
    T59a's ``by_category`` breakdown, mirroring :data:`ci_gate.MAX_REGRESSION`
    semantics (a drop of EXACTLY ``max_regression`` is allowed).

Pure stdlib: no dependencies, no network. Both functions are deterministic and
return JSON-serializable results.
"""
from __future__ import annotations


def evaluate_extraction_failure(
    panel: dict,
    *,
    threshold: float,
    min_fields: int,
) -> dict:
    """Decide the extraction-failure-rate alert from a Week-2 panel.

    ``panel`` is the dict returned by :func:`panels.aggregate_week2_events`; the
    failure rate is the non-``ok`` fraction of ``extraction.field`` outcomes,
    i.e. ``(total - ok) / total`` where ``total``/``ok`` come from
    ``panel["extraction"]``.

    The alert fires iff the rate STRICTLY exceeds ``threshold`` AND at least
    ``min_fields`` observations back it (a volume floor to avoid noise on low
    traffic). A rate equal to ``threshold`` does not fire. Below the floor or on
    an empty panel it does not fire, and ``rate`` is ``0.0`` when ``total`` is
    zero (divide-by-zero safe).

    Returns ``{"firing": bool, "rate": float, "failed": int, "total": int}``.
    """
    extraction = panel["extraction"]
    total = extraction["total"]
    ok = extraction["ok"]
    failed = total - ok
    rate = (failed / total) if total else 0.0
    firing = rate > threshold and total >= min_fields
    return {
        "firing": firing,
        "rate": rate,
        "failed": failed,
        "total": total,
    }


def detect_eval_regression(
    baseline_by_category: dict,
    current_by_category: dict,
    max_regression: float = 0.05,
) -> list[str]:
    """Return eval categories whose pass rate regressed beyond ``max_regression``.

    Both inputs are the T59a ``by_category`` shape,
    ``{category: {"passed", "total", "pass_rate"}}``. For each category present
    in ``baseline_by_category``:

      * ``baseline_rate`` is ``baseline[cat]["pass_rate"]``;
      * ``current_rate`` is ``current[cat]["pass_rate"]`` if the category is
        present in ``current_by_category`` else ``0.0`` (a missing current
        category is a FULL drop).

    The category regresses iff ``baseline_rate - current_rate > max_regression``
    (a drop of EXACTLY ``max_regression`` is allowed — a strict ``>`` with the
    same 1e-9 float-tolerance guard as :func:`ci_gate.regression_gate`).
    Categories present only in ``current`` are ignored. The regressed category
    names are returned as a SORTED list.
    """
    regressed: list[str] = []
    for category, baseline_stats in baseline_by_category.items():
        baseline_rate = baseline_stats["pass_rate"]
        current_stats = current_by_category.get(category)
        current_rate = current_stats["pass_rate"] if current_stats is not None else 0.0
        # Mirror ``ci_gate.regression_gate``: an epsilon guard so a drop of
        # exactly ``max_regression`` (which floating-point may render as e.g.
        # 0.050000000000000044) is treated as allowed, not a regression.
        if baseline_rate - current_rate > max_regression + 1e-9:
            regressed.append(category)
    return sorted(regressed)
