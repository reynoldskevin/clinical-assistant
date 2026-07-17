"""T59b acceptance tests (LOCKED) — ALERTS.md documents the three Week-2 alerts.

`ALERTS.md` shipped with five Week-1 alerts, each with an on-call runbook (guarded
by the T41 `test_alerts_doc.py`, which must stay green). This ticket adds three
Week-2 alerts — extraction-failure rate, RAG-retrieval latency, and eval-regression
(>5% per category) — each with a runbook. Static-text guard, mirrors
test_architecture_doc.py.
"""
import os
import re

_HERE = os.path.dirname(__file__)
DOC = os.path.join(_HERE, "..", "..", "ALERTS.md")


def _raw() -> str:
    with open(DOC) as fh:
        return fh.read()


def _norm() -> str:
    return re.sub(r"\s+", " ", _raw().lower())


def _has_any(text, options):
    return any(o in text for o in options)


def test_three_new_alerts_named():
    n = _norm()
    assert _has_any(n, ["extraction-failure", "extraction failure"]), "no extraction-failure alert"
    assert _has_any(n, ["rag-retrieval latency", "rag retrieval latency", "retrieval latency"]), "no RAG-retrieval latency alert"
    assert _has_any(n, ["eval-regression", "eval regression"]), "no eval-regression alert"


def test_eval_regression_alert_states_the_5pct_per_category_rule():
    n = _norm()
    assert _has_any(n, ["per category", "per-category", "by category", "any category"])
    assert _has_any(n, ["5%", "5 %", "0.05"])


def test_each_new_alert_has_a_runbook():
    # The five Week-1 alerts each carry an "On-call response" runbook; the three
    # new alerts must too, so the count grows from 5 to at least 8.
    assert _raw().lower().count("on-call response") >= 8


def test_new_alerts_reference_their_backing_signals():
    n = _norm()
    # extraction-failure derives from the extraction.field outcomes (T57);
    # eval-regression from the per-category eval breakdown.
    assert _has_any(n, ["extraction.field", "extraction field"])
    assert _has_any(n, ["by_category", "per-category", "per category"])
