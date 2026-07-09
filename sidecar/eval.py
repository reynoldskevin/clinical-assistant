"""Sidecar eval harness.

Model-agnostic evaluation of the clinical agent. The agent runner is injected
so grading stays deterministic and offline: a runner is a callable
``runner(question: str, pid: int) -> tuple[str, dict]`` where the dict has the
shape of ``TraceCollector.summary()``. Cases are declared in YAML and each case
carries a list of one-key grader specs applied against the runner output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import yaml

Runner = Callable[[str, int], tuple[str, dict]]


@dataclass
class EvalCase:
    """A single evaluation case."""

    name: str
    question: str
    pid: int
    graders: list[dict]


@dataclass
class EvalResult:
    """The outcome of running one :class:`EvalCase`."""

    name: str
    passed: bool
    failures: list[str]


def load_cases(yaml_text: str) -> list[EvalCase]:
    """Parse a YAML list of case dicts into :class:`EvalCase` objects."""
    raw = yaml.safe_load(yaml_text) or []
    return [
        EvalCase(
            name=item["name"],
            question=item["question"],
            pid=item["pid"],
            graders=item["graders"],
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
    return EvalResult(name=case.name, passed=not failures, failures=failures)


def run_suite(cases: list[EvalCase], runner: Runner) -> dict:
    """Run every case and return a tally plus per-case results."""
    results = [run_case(case, runner) for case in cases]
    return {
        "passed": sum(1 for r in results if r.passed),
        "total": len(cases),
        "results": results,
    }
