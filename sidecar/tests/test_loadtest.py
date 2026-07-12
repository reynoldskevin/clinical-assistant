"""T42 acceptance tests (LOCKED) — load-test summary math.

The load-test harness's number-crunching (percentiles, throughput, error rate)
must be correct and deterministic so the captured baselines are trustworthy; the
HTTP driver / process sampling are operational and not unit-tested here.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "perf"))

from loadtest import percentile, summarize


def test_percentile_nearest_rank_on_1_to_100():
    values = list(range(1, 101))  # already sorted 1..100
    assert percentile(values, 0.50) == 50
    assert percentile(values, 0.95) == 95
    assert percentile(values, 0.99) == 99


def test_percentile_edges():
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0.0) == 10.0
    assert percentile(values, 1.0) == 40.0


def test_summarize_structure_and_throughput():
    latencies = [float(x) for x in range(1, 101)]  # 100 successful requests
    s = summarize(latencies, elapsed_s=2.0, errors=0)
    assert s["requests"] == 100
    assert s["errors"] == 0
    assert s["error_rate"] == 0.0
    assert s["throughput_rps"] == 50.0          # 100 req / 2 s
    lat = s["latency_ms"]
    assert lat["p50"] == 50
    assert lat["p95"] == 95
    assert lat["p99"] == 99
    assert lat["min"] == 1
    assert lat["max"] == 100
    assert lat["mean"] == 50.5


def test_summarize_counts_errors_in_total_and_rate():
    latencies = [float(x) for x in range(1, 91)]  # 90 ok
    s = summarize(latencies, elapsed_s=1.0, errors=10)
    assert s["requests"] == 100                  # 90 ok + 10 errors
    assert s["errors"] == 10
    assert s["error_rate"] == 0.1
    assert s["throughput_rps"] == 100.0


def test_summarize_empty_is_safe():
    s = summarize([], elapsed_s=0.0, errors=0)
    assert s["requests"] == 0
    assert s["error_rate"] == 0.0
    assert s["throughput_rps"] == 0.0
    assert s["latency_ms"]["p95"] == 0
