"""Sidecar eval harness.

Model-agnostic evaluation of the clinical agent. The agent runner is injected
so grading stays deterministic and offline: a runner is a callable
``runner(question: str, pid: int) -> tuple[str, dict]`` where the dict has the
shape of ``TraceCollector.summary()``. Cases are declared in YAML and each case
carries a list of one-key grader specs applied against the runner output.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable

import yaml

import factory
from events import EVAL_RUN, log_event

Runner = Callable[[str, int], tuple[str, dict]]


@dataclass
class EvalCase:
    """A single evaluation case."""

    name: str
    question: str
    pid: int
    graders: list[dict]
    uc: int | None = None
    category: str | None = None
    guards: dict | None = None


@dataclass
class EvalResult:
    """The outcome of running one :class:`EvalCase`."""

    name: str
    passed: bool
    failures: list[str]
    category: str | None = None


def load_cases(yaml_text: str) -> list[EvalCase]:
    """Parse a YAML list of case dicts into :class:`EvalCase` objects."""
    raw = yaml.safe_load(yaml_text) or []
    return [
        EvalCase(
            name=item["name"],
            question=item["question"],
            pid=item["pid"],
            graders=item["graders"],
            uc=item.get("uc"),
            category=item.get("category"),
            guards=item.get("guards"),
        )
        for item in raw
    ]


def _grade(grader: dict, text: str, trace: dict) -> str | None:
    """Apply one grader spec; return a failure reason, or None if it passes."""
    if len(grader) != 1:
        return f"invalid grader (expected one key): {grader!r}"

    key, value = next(iter(grader.items()))
    lower_text = text.lower()
    tool_calls = trace.get("tool_calls", 0)

    if key == "contains":
        if str(value).lower() not in lower_text:
            return f"contains: {value!r} not found in output"
        return None
    if key == "excludes":
        if str(value).lower() in lower_text:
            return f"excludes: {value!r} unexpectedly found in output"
        return None
    if key == "contains_any":
        values = value if isinstance(value, list) else [value]
        if not any(str(s).lower() in lower_text for s in values):
            return f"contains_any: none of {values!r} found in output"
        return None
    if key == "tool_used":
        if (tool_calls >= 1) != bool(value):
            return f"tool_used: expected {bool(value)} (tool_calls={tool_calls})"
        return None
    if key == "max_tool_calls":
        if tool_calls > value:
            return f"max_tool_calls: {tool_calls} > {value}"
        return None
    if key == "no_tool_failures":
        failures = trace.get("tool_failures", 0)
        if failures != 0:
            return f"no_tool_failures: {failures} tool failure(s)"
        return None

    return f"unknown grader: {key}"


def run_case(case: EvalCase, runner: Runner) -> EvalResult:
    """Run a case through the runner and grade the result."""
    text, trace = runner(case.question, case.pid)
    failures = [
        reason
        for grader in case.graders
        if (reason := _grade(grader, text, trace)) is not None
    ]
    return EvalResult(name=case.name, passed=not failures, failures=failures, category=case.category)


def run_suite(cases: list[EvalCase], runner: Runner) -> dict:
    """Run every case and return a tally plus per-case results."""
    results = [run_case(case, runner) for case in cases]
    return {
        "passed": sum(1 for r in results if r.passed),
        "total": len(cases),
        "results": results,
    }


def run_all(evals_dir: str, runner: Runner) -> dict:
    """Load and run every ``*.yaml`` under ``evals_dir`` and aggregate the result.

    Returns a summary dict with the overall ``passed``/``total``/``pass_rate``, a
    ``by_file`` breakdown keyed by filename stem, the flat ``results`` list, and
    the union of declared ``ucs``/``categories`` across all LOADED cases
    (regardless of pass/fail). ``pass_rate`` is ``0.0`` when ``total == 0``.
    """
    by_file: dict[str, dict[str, int]] = {}
    results: list[EvalResult] = []
    ucs: set[int] = set()
    categories: set[str] = set()

    for path in sorted(glob.glob(os.path.join(evals_dir, "*.yaml"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        with open(path) as fh:
            cases = load_cases(fh.read())
        file_results = [run_case(case, runner) for case in cases]
        results.extend(file_results)
        by_file[stem] = {
            "passed": sum(1 for r in file_results if r.passed),
            "total": len(file_results),
        }
        for case in cases:
            if case.uc is not None:
                ucs.add(case.uc)
            if case.category is not None:
                categories.add(case.category)

    passed = sum(1 for r in results if r.passed)
    total = len(results)

    by_category: dict[str, dict[str, float]] = {}
    for result in results:
        key = result.category if result.category is not None else "uncategorized"
        bucket = by_category.setdefault(key, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if result.passed:
            bucket["passed"] += 1
    for bucket in by_category.values():
        bucket["pass_rate"] = bucket["passed"] / bucket["total"]

    summary = {
        "passed": passed,
        "total": total,
        "pass_rate": (passed / total) if total else 0.0,
        "by_file": by_file,
        "results": results,
        "ucs": ucs,
        "categories": categories,
        "by_category": by_category,
    }
    log_event(
        EVAL_RUN,
        factory.new_correlation_id(),
        passed=summary["passed"],
        total=summary["total"],
    )
    return summary


def gate(summary: dict, threshold: float) -> bool:
    """Pure pass/fail gate: True iff the pass rate meets or exceeds ``threshold``."""
    return summary["pass_rate"] >= threshold


def build_offline_runner() -> Runner:
    """A deterministic, no-LLM runner used as the default offline sweep runner.

    It never touches the network and returns a fixed benign response, so the
    offline path needs no API key. Its exact output is not asserted by tests.
    """
    def runner(question: str, pid: int) -> tuple[str, dict]:
        return "", {"tool_calls": 0, "tool_failures": 0}

    return runner


def _b64url(raw: bytes) -> str:
    """URL-safe base64 without padding (JWT segment encoding)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_eval_jwt(pid: int, signing_key: str, *, ttl_seconds: int = 300) -> str:
    """Mint a pid-scoped HS256 boundary token matching ScopedTokenService.

    The app-side boundary (summary.php / read.php) verifies an HS256 JWT with the
    shared signing key and checks ``aud`` + ``pid``. This mirrors that payload so
    the live eval can authenticate its chart reads without a browser session. It
    is eval-only tooling (stdlib HMAC), never used in the request path.
    """
    import hashlib
    import hmac
    import time

    header = {"typ": "JWT", "alg": "HS256"}
    now = int(time.time())
    payload = {
        "cid": 1,
        "usr": "eval",
        "pid": int(pid),
        "purpose": "eval",
        "aud": "oe-ai-agent-boundary",
        "iat": now,
        "exp": now + ttl_seconds,
        "scope": "read",
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    sig = hmac.new(signing_key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url(sig)


def build_eval_agent_tools(chart_boundary, message_creator, observer) -> list:
    """Assemble the SAME extra-tool set as ``server.default_agent_builder``.

    Kept as a standalone helper so a parity test can assert the eval agent wires
    every production tool (encounter, results, medications, search, documents,
    get_intake_form, evidence_retriever) — the live sweep must exercise the real
    agent, not an impoverished subset. Pure construction; safe to call offline
    with fakes (no network, no API key).
    """
    from factory import (
        build_documents_tools,
        build_encounter_tools,
        build_intake_tool,
        build_medications_tool,
        build_results_tool,
        build_search_tool,
    )
    from retrieval import build_evidence_retriever_tool, get_guideline_index

    return (
        build_encounter_tools(chart_boundary)
        + [
            build_results_tool(chart_boundary),
            build_medications_tool(chart_boundary),
            build_search_tool(chart_boundary),
        ]
        + build_documents_tools(chart_boundary)
        + [
            build_intake_tool(chart_boundary, message_creator),
            build_evidence_retriever_tool(get_guideline_index(), tracer=observer),
        ]
    )


def build_live_runner() -> Runner:
    """Construct a runner that drives the REAL ClaudeAgent over the boundary.

    Everything anthropic/network-related is imported lazily INSIDE this function
    so the offline path never needs the SDK or an API key. The agent is built with
    the SAME tool set as ``server.py``'s ``default_agent_builder`` (encounter,
    results, medications, search, documents, get_intake_form, evidence_retriever)
    so the sweep exercises the production agent, not an impoverished subset. Chart
    reads authenticate with a per-pid token: an explicit ``OE_AI_AGENT_EVAL_JWT``
    if given, else one minted from ``OE_AI_AGENT_SIGNING_KEY`` (the shared key).
    """
    from agent import ClaudeAgent
    from factory import build_boundary, build_chart_boundary, build_message_creator
    from observability import TraceCollector

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is required for the live eval runner.")

    summary_url = os.environ.get(
        "OE_AI_AGENT_SUMMARY_URL",
        "http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php",
    )
    read_url = os.environ.get("OE_AI_AGENT_READ_URL") or summary_url.replace("summary.php", "read.php")
    static_jwt = os.environ.get("OE_AI_AGENT_EVAL_JWT", "")
    signing_key = os.environ.get("OE_AI_AGENT_SIGNING_KEY", "")
    max_tool_calls = int(os.environ.get("OE_AI_AGENT_MAX_TOOL_CALLS") or "8")
    message_creator = build_message_creator(api_key)

    def _jwt_for(pid: int) -> str:
        if static_jwt:
            return static_jwt
        if signing_key:
            return mint_eval_jwt(pid, signing_key)
        return ""

    def runner(question: str, pid: int) -> tuple[str, dict]:
        jwt = _jwt_for(pid)
        boundary = build_boundary(summary_url, jwt)
        chart_boundary = build_chart_boundary(read_url, jwt)
        observer = TraceCollector()
        agent = ClaudeAgent(
            message_creator,
            boundary,
            observer=observer,
            extra_tools=build_eval_agent_tools(chart_boundary, message_creator, observer),
            max_tool_calls=max_tool_calls,
        )
        answer = agent.run(question, pid)
        return answer, observer.summary()

    return runner


def _default_evals_dir() -> str:
    """The packaged ``evals/`` dir, resolved relative to this file."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "evals")


def main(argv: list[str], runner: Runner | None = None) -> int:
    """Run the sweep and return an exit code (0 = gate passed, 1 = failed).

    The runner is picked in priority order: the injected ``runner`` param if
    given, else the live runner when ``--live`` is set, else the deterministic
    offline runner. The live runner is NEVER constructed on the offline path.
    """
    parser = argparse.ArgumentParser(prog="eval", description="Run the sidecar eval sweep.")
    parser.add_argument("--live", action="store_true", help="Drive the real agent+LLM.")
    parser.add_argument("--threshold", type=float, default=0.9, help="Minimum pass rate.")
    parser.add_argument("--dir", default=_default_evals_dir(), help="Directory of eval YAMLs.")
    args = parser.parse_args(argv)

    if runner is None:
        runner = build_live_runner() if args.live else build_offline_runner()

    summary = run_all(args.dir, runner)

    for stem in sorted(summary["by_file"]):
        stats = summary["by_file"][stem]
        print(f"  {stem}: {stats['passed']}/{stats['total']}")
    print(f"TOTAL: {summary['passed']}/{summary['total']} (pass_rate={summary['pass_rate']:.3f})")
    print(f"threshold={args.threshold:.3f}")

    return 0 if gate(summary, args.threshold) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
