"""T42 guard test (LOCKED) — the captured performance baselines exist.

METRICS_WEEK1.md records the CPU / memory / latency / throughput baselines under
the load-test scenarios so future changes can be measured against them. This guard
pins that the doc exists and covers the four required metric families.
"""
import os

BASELINES = os.path.join(os.path.dirname(__file__), "..", "..", "METRICS_WEEK1.md")


def _text():
    with open(BASELINES) as fh:
        return fh.read().lower()


def test_baselines_doc_exists():
    assert os.path.exists(BASELINES)


def test_baselines_cover_the_four_metric_families():
    t = _text()
    assert "cpu" in t
    assert "memory" in t or "rss" in t
    assert "latency" in t
    assert "throughput" in t


def test_baselines_document_scenarios_and_percentiles():
    t = _text()
    assert "p95" in t
    assert "scenario" in t
    # the harness that produced them is referenced so they can be re-run
    assert "loadtest" in t
