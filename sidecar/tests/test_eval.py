"""T13 acceptance tests (LOCKED) for the sidecar eval harness.

Model-agnostic: the agent-runner is injected, so grading is deterministic. A runner
returns (text, trace_dict) where trace_dict is TraceCollector.summary() shape.
"""
from eval import EvalCase, load_cases, run_case, run_suite

YAML = """
- name: happy
  question: How is the patient?
  pid: 42
  graders:
    - contains: stable
    - tool_used: true
- name: negative
  question: Is the patient critical?
  pid: 42
  graders:
    - contains: critical
"""


def _runner_stable(question, pid):
    # a fixed agent behavior: says "stable", used one tool, no failures
    return ("The patient is stable.", {"tool_calls": 1, "tool_failures": 0})


def test_load_cases_from_yaml():
    cases = load_cases(YAML)
    assert [c.name for c in cases] == ["happy", "negative"]
    happy = cases[0]
    assert isinstance(happy, EvalCase)
    assert happy.question == "How is the patient?"
    assert happy.pid == 42
    assert happy.graders == [{"contains": "stable"}, {"tool_used": True}]


def test_contains_grader_pass_and_fail():
    passing = EvalCase("c", "q", 42, [{"contains": "STABLE"}])   # case-insensitive
    assert run_case(passing, _runner_stable).passed is True

    failing = EvalCase("c", "q", 42, [{"contains": "critical"}])
    r = run_case(failing, _runner_stable)
    assert r.passed is False
    assert r.failures  # a reason recorded


def test_excludes_grader():
    ok = EvalCase("c", "q", 42, [{"excludes": "critical"}])
    assert run_case(ok, _runner_stable).passed is True
    bad = EvalCase("c", "q", 42, [{"excludes": "stable"}])
    assert run_case(bad, _runner_stable).passed is False


def test_tool_used_grader():
    used = EvalCase("c", "q", 42, [{"tool_used": True}])
    assert run_case(used, _runner_stable).passed is True
    # runner used a tool, so tool_used: false must FAIL
    not_used = EvalCase("c", "q", 42, [{"tool_used": False}])
    assert run_case(not_used, _runner_stable).passed is False


def test_max_tool_calls_and_no_failures_graders():
    within = EvalCase("c", "q", 42, [{"max_tool_calls": 2}, {"no_tool_failures": True}])
    assert run_case(within, _runner_stable).passed is True

    def runner_failed(q, pid):
        return ("could not read", {"tool_calls": 1, "tool_failures": 1})

    strict = EvalCase("c", "q", 42, [{"no_tool_failures": True}])
    assert run_case(strict, runner_failed).passed is False


def test_unknown_grader_is_a_hard_failure():
    weird = EvalCase("c", "q", 42, [{"bogus_grader": 1}])
    assert run_case(weird, _runner_stable).passed is False


def test_run_suite_tallies():
    cases = load_cases(YAML)  # happy passes, negative fails against _runner_stable
    summary = run_suite(cases, _runner_stable)
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert len(summary["results"]) == 2
