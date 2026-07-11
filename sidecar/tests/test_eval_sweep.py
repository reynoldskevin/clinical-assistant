"""T26 acceptance tests (LOCKED) — eval sweep aggregator, pass-rate gate, CLI,
coverage completeness, and the GitLab CI wiring.

All deterministic: the sweep runs against an injected runner (no live LLM). The
live path is selected by a flag but is never constructed here.
"""
import os

import yaml

from eval import gate, main, run_all

EVALS_DIR = os.path.join(os.path.dirname(__file__), "..", "evals")
GITLAB_CI = os.path.join(os.path.dirname(__file__), "..", "..", ".gitlab-ci.yml")


def _write(dirpath, name, text):
    with open(os.path.join(dirpath, name), "w") as fh:
        fh.write(text)


def _mixed_dir(tmp_path):
    """Two eval files: one case passes for a runner emitting 'alpha', one fails."""
    _write(str(tmp_path), "alpha.yaml", (
        "- name: a_pass\n"
        "  question: q\n"
        "  pid: 1\n"
        "  uc: 1\n"
        "  category: grounding\n"
        "  graders:\n"
        "    - contains: alpha\n"
    ))
    _write(str(tmp_path), "beta.yaml", (
        "- name: b_fail\n"
        "  question: q\n"
        "  pid: 1\n"
        "  uc: 2\n"
        "  category: absence\n"
        "  graders:\n"
        "    - contains: beta\n"
    ))
    return lambda question, pid: ("alpha only", {"tool_calls": 0, "tool_failures": 0})


# --- run_all aggregation -------------------------------------------------------

def test_run_all_aggregates_across_files(tmp_path):
    runner = _mixed_dir(tmp_path)
    s = run_all(str(tmp_path), runner)

    assert s["passed"] == 1
    assert s["total"] == 2
    assert s["pass_rate"] == 0.5
    assert s["by_file"]["alpha"] == {"passed": 1, "total": 1}
    assert s["by_file"]["beta"] == {"passed": 0, "total": 1}
    assert s["ucs"] == {1, 2}
    assert s["categories"] == {"grounding", "absence"}


def test_run_all_empty_dir_is_zero_not_crash(tmp_path):
    s = run_all(str(tmp_path), lambda q, p: ("", {}))
    assert s["total"] == 0
    assert s["pass_rate"] == 0.0


# --- gate ----------------------------------------------------------------------

def test_gate_is_pass_rate_at_or_above_threshold():
    assert gate({"pass_rate": 0.9}, 0.9) is True     # at threshold -> pass
    assert gate({"pass_rate": 1.0}, 0.9) is True
    assert gate({"pass_rate": 0.89}, 0.9) is False    # below -> fail
    assert gate({"pass_rate": 0.0}, 0.01) is False


# --- CLI exit code (offline / injected runner) ---------------------------------

def test_main_exit_zero_when_threshold_met(tmp_path):
    runner = _mixed_dir(tmp_path)  # pass_rate = 0.5
    assert main(["--dir", str(tmp_path), "--threshold", "0.4"], runner=runner) == 0


def test_main_exit_one_when_threshold_missed(tmp_path):
    runner = _mixed_dir(tmp_path)  # pass_rate = 0.5
    assert main(["--dir", str(tmp_path), "--threshold", "0.6"], runner=runner) == 1


# --- coverage completeness over the real evals/ dir ----------------------------

def test_packaged_evals_cover_uc1_through_uc6_and_all_categories():
    # ucs/categories are read from the loaded cases regardless of pass/fail, so a
    # trivial runner is fine here — this asserts the SUITE's declared coverage.
    s = run_all(EVALS_DIR, lambda q, p: ("", {"tool_calls": 0, "tool_failures": 0}))
    assert {1, 2, 3, 4, 5, 6} <= s["ucs"], f"missing UC coverage: {s['ucs']}"
    required = {"grounding", "absence", "safety", "deferral", "synthesis", "data_quality"}
    assert required <= s["categories"], f"missing categories: {required - s['categories']}"


# --- GitLab CI wiring ----------------------------------------------------------

def test_gitlab_ci_defines_offline_gate_and_live_sweep():
    with open(GITLAB_CI) as fh:
        raw = fh.read()
    data = yaml.safe_load(raw)
    assert isinstance(data, dict)
    # Per-push offline gate + the non-blocking live scored sweep.
    assert "eval:offline" in data
    assert "eval:live" in data
    # The live sweep runs the real agent, so it must reference the API-key secret.
    assert "ANTHROPIC_API_KEY" in raw
