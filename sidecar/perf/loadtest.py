"""Dependency-free load-test harness for capturing sidecar performance baselines.

This module drives a configurable number of HTTP requests at a target URL with
bounded concurrency, measures per-request wall latency, and crunches the results
into deterministic summary statistics (nearest-rank percentiles, throughput,
error rate). It optionally samples a target process's CPU/RSS during the run.

The captured numbers back the sidecar performance baselines recorded in
METRICS_WEEK1.md. Everything here is Python standard library only — no third-party
dependencies — so it can run anywhere the interpreter runs.

Usage:
    python loadtest.py --url http://localhost:8080/health --n 200 --concurrency 10
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def percentile(sorted_values, q):
    """Nearest-rank percentile of an ALREADY-SORTED list.

    ``q`` is in [0, 1]. Returns 0 for an empty list.
    """
    n = len(sorted_values)
    if n == 0:
        return 0
    idx = max(0, min(n - 1, math.ceil(q * n) - 1))
    return sorted_values[idx]


def summarize(latencies_ms, elapsed_s, errors):
    """Summarize a batch of latencies into a stats dict.

    ``requests`` counts every attempt (successes + errors). Percentiles/min/max
    are computed on a SORTED COPY so the caller's list is never mutated.
    """
    successes = len(latencies_ms)
    requests = successes + errors

    error_rate = errors / requests if requests > 0 else 0.0
    throughput_rps = requests / elapsed_s if elapsed_s > 0 else 0.0

    if successes > 0:
        ordered = sorted(latencies_ms)
        latency = {
            "p50": percentile(ordered, 0.50),
            "p95": percentile(ordered, 0.95),
            "p99": percentile(ordered, 0.99),
            "min": ordered[0],
            "max": ordered[-1],
            "mean": sum(ordered) / successes,
        }
    else:
        latency = {"p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "mean": 0}

    return {
        "requests": requests,
        "errors": errors,
        "error_rate": error_rate,
        "throughput_rps": throughput_rps,
        "latency_ms": latency,
    }


def _do_request(url, method, headers, body, timeout):
    """Fire a single request. Return (latency_ms, is_error).

    An HTTPError (4xx/5xx) still counts as a completed request — the server
    answered — so we record its latency and mark it a success. Only connection
    errors / timeouts count as errors (no latency recorded).
    """
    req = urllib.request.Request(url, data=body, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    start = time.perf_counter()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp.read()
        resp.close()
        return (time.perf_counter() - start) * 1000.0, False
    except urllib.error.HTTPError as exc:
        # Server responded (4xx/5xx) — a completed request.
        try:
            exc.read()
            exc.close()
        except Exception:
            pass
        return (time.perf_counter() - start) * 1000.0, False
    except Exception:
        # Connection error / timeout / DNS failure — a real error.
        return 0.0, True


def run_scenario(url, n, concurrency, method="GET", headers=None, body=None, timeout=120):
    """Fire ``n`` requests at ``url`` with up to ``concurrency`` in flight.

    Returns ``(latencies_ms, elapsed_s, errors)``.
    """
    latencies_ms = []
    errors = 0

    batch_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(_do_request, url, method, headers, body, timeout)
            for _ in range(n)
        ]
        for future in futures:
            latency_ms, is_error = future.result()
            if is_error:
                errors += 1
            else:
                latencies_ms.append(latency_ms)
    elapsed_s = time.perf_counter() - batch_start

    return latencies_ms, elapsed_s, errors


def sample_process(pid):
    """Sample a process's CPU% and RSS (MB) via ``ps``.

    Returns ``{"cpu_pct": float, "rss_mb": float}``; zeros on any failure.
    """
    try:
        result = subprocess.run(
            ["ps", "-o", "%cpu=,rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=True,
        )
        line = result.stdout.strip()
        if not line:
            return {"cpu_pct": 0.0, "rss_mb": 0.0}
        parts = line.split()
        cpu_pct = float(parts[0])
        rss_kb = float(parts[1])
        return {"cpu_pct": cpu_pct, "rss_mb": rss_kb / 1024.0}
    except Exception:
        return {"cpu_pct": 0.0, "rss_mb": 0.0}


class _ProcessSampler(threading.Thread):
    """Background daemon that tracks peak CPU%/RSS of a process during a run."""

    def __init__(self, pid, interval=0.2):
        super().__init__(daemon=True)
        self._pid = pid
        self._interval = interval
        self._stop_event = threading.Event()
        self.cpu_pct_peak = 0.0
        self.rss_mb_peak = 0.0

    def run(self):
        while not self._stop_event.is_set():
            sample = sample_process(self._pid)
            self.cpu_pct_peak = max(self.cpu_pct_peak, sample["cpu_pct"])
            self.rss_mb_peak = max(self.rss_mb_peak, sample["rss_mb"])
            self._stop_event.wait(self._interval)

    def stop(self):
        self._stop_event.set()


def _parse_headers(header_args):
    headers = {}
    for raw in header_args or []:
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def main(argv):
    parser = argparse.ArgumentParser(
        description="Dependency-free load-test harness for sidecar baselines."
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--method", default="GET")
    parser.add_argument("--header", action="append", dest="headers", default=[])
    parser.add_argument("--body-file")
    parser.add_argument("--body")
    parser.add_argument("--pid", type=int)
    args = parser.parse_args(argv)

    headers = _parse_headers(args.headers)

    body = None
    if args.body_file:
        with open(args.body_file, "rb") as handle:
            body = handle.read()
    elif args.body is not None:
        body = args.body.encode("utf-8")

    sampler = None
    if args.pid is not None:
        sampler = _ProcessSampler(args.pid)
        sampler.start()

    latencies_ms, elapsed_s, errors = run_scenario(
        args.url,
        args.n,
        args.concurrency,
        method=args.method,
        headers=headers,
        body=body,
    )

    if sampler is not None:
        sampler.stop()
        sampler.join(timeout=1.0)

    output = summarize(latencies_ms, elapsed_s, errors)
    output["elapsed_s"] = elapsed_s
    output["scenario"] = {
        "url": args.url,
        "n": args.n,
        "concurrency": args.concurrency,
        "method": args.method,
    }
    if sampler is not None:
        output["process"] = {
            "pid": args.pid,
            "cpu_pct_peak": sampler.cpu_pct_peak,
            "rss_mb_peak": sampler.rss_mb_peak,
        }

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
