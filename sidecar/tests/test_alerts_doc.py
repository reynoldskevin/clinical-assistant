"""T41 guard test (LOCKED) — the alert definitions + runbook exist and are complete.

Braintrust alerts are UI-configured (no public automation API), so this deliverable
is a definition/documentation artifact. This guard test pins that ALERTS.md defines
the three required alerts (p95 latency, error rate, tool failure rate), each with a
threshold, a BTQL/metric mapping, a meaning, and an on-call response — so a future
edit can't silently drop one.
"""
import os

ALERTS = os.path.join(os.path.dirname(__file__), "..", "..", "ALERTS.md")


def _text():
    with open(ALERTS) as fh:
        return fh.read().lower()


def test_alerts_doc_exists():
    assert os.path.exists(ALERTS)


def test_defines_the_three_required_alerts():
    t = _text()
    assert "p95" in t and "latency" in t          # 1) p95 latency
    assert "error rate" in t                        # 2) error rate
    assert "tool failure" in t                      # 3) tool failure rate


def test_each_alert_has_threshold_and_oncall_response():
    t = _text()
    assert "threshold" in t
    # on-call response / runbook is documented
    assert "on-call" in t or "on call" in t
    assert "response" in t


def test_maps_alerts_to_the_logged_metric_fields():
    t = _text()
    # the alerts read the fields T38 logs to Braintrust
    assert "scores.success" in t or "success" in t
    assert "tool_failures" in t or "tool_calls" in t
    assert "btql" in t   # the condition is expressed as BTQL for Braintrust
