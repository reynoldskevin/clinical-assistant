"""T66 acceptance tests (LOCKED) — CI hardening: dependency audit + security scan.

Hardening deferred from T52. The eval gate blocks merges on behavioural
regressions, but nothing audits the sidecar dependency tree for known CVEs or
scans the Python for insecure patterns. T66 adds a `security` tier to the GitLab
pipeline: two blocking, secret-free jobs — `security:deps` (pip-audit) and
`security:scan` (bandit) — that run on every merge request and branch push,
mirroring how `eval:offline` is wired as a per-push blocking gate.

These are CONFIG-CONTRACT tests (offline, deterministic — no network, no tool
run): they parse `.gitlab-ci.yml` and `sidecar/requirements-security.txt` and
assert the pipeline declares the jobs correctly. The jobs themselves run the real
tools in CI. Mirrors the T52 `GITLAB_CI` assertions in `test_ci_gate.py`.
"""
import json
import os

import yaml


_HERE = os.path.dirname(__file__)
GITLAB_CI = os.path.join(_HERE, "..", "..", ".gitlab-ci.yml")
REQ_SECURITY = os.path.join(_HERE, "..", "requirements-security.txt")

SECURITY_JOBS = ("security:deps", "security:scan")


def _pipeline() -> dict:
    with open(GITLAB_CI) as fh:
        return yaml.safe_load(fh.read())


def _job_blob(job: dict) -> str:
    return json.dumps(job)


def _all_script(job: dict) -> str:
    """Concatenate before_script + script into one lowercased blob."""
    parts = list(job.get("before_script", []) or []) + list(job.get("script", []) or [])
    return " ".join(parts).lower()


# --- the security stage + jobs exist -----------------------------------------

def test_security_stage_is_declared():
    data = _pipeline()
    assert "stages" in data
    assert "security" in data["stages"], f"stages missing 'security': {data['stages']}"


def test_both_security_jobs_exist_in_the_security_stage():
    data = _pipeline()
    for job_name in SECURITY_JOBS:
        assert job_name in data, f"missing CI job {job_name!r}"
        assert data[job_name].get("stage") == "security", (
            f"{job_name}: stage is {data[job_name].get('stage')!r}, expected 'security'"
        )


# --- the jobs are blocking on every PR ---------------------------------------

def test_security_jobs_are_blocking_never_manual_or_allow_failure():
    data = _pipeline()
    for job_name in SECURITY_JOBS:
        job = data[job_name]
        assert job.get("allow_failure") is not True, f"{job_name}: job-level allow_failure"
        for rule in job.get("rules", []) or []:
            assert rule.get("when") != "manual", f"{job_name}: a rule is manual"
            assert rule.get("allow_failure") is not True, f"{job_name}: a rule allows failure"


def test_security_jobs_run_on_merge_requests_not_only_schedule_or_tag():
    # A job with no explicit rules inherits the top-level workflow rules (which
    # include merge_request_event and branch pushes), so it runs on every PR. If a
    # job DOES declare rules, they must not restrict it to schedule/tag only.
    data = _pipeline()
    for job_name in SECURITY_JOBS:
        rules = data[job_name].get("rules", []) or []
        if not rules:
            continue
        blob = json.dumps(rules).lower()
        assert ("merge_request" in blob) or ("ci_commit_branch" in blob), (
            f"{job_name}: rules do not cover MR / branch pushes: {rules}"
        )
        # Must not be gated behind schedule/tag exclusively.
        assert not (("schedule" in blob or "ci_commit_tag" in blob)
                    and "merge_request" not in blob and "ci_commit_branch" not in blob), (
            f"{job_name}: restricted to schedule/tag only"
        )


def test_security_jobs_carry_no_secret():
    data = _pipeline()
    for job_name in SECURITY_JOBS:
        assert "ANTHROPIC_API_KEY" not in _job_blob(data[job_name]), (
            f"{job_name}: must not reference a secret"
        )


# --- the jobs run the right tools --------------------------------------------

def test_dependency_audit_runs_pip_audit_against_sidecar_requirements():
    data = _pipeline()
    script = _all_script(data["security:deps"])
    assert "pip-audit" in script, "security:deps must run pip-audit"
    assert "sidecar/requirements" in script or "requirements.txt" in script, (
        "security:deps must audit the sidecar requirements manifest"
    )


def test_security_scan_runs_bandit_over_the_sidecar_source():
    data = _pipeline()
    script = _all_script(data["security:scan"])
    assert "bandit" in script, "security:scan must run bandit"
    assert "sidecar" in script, "security:scan must target the sidecar source"


# --- pinned tooling manifest -------------------------------------------------

def test_requirements_security_pins_both_tools():
    with open(REQ_SECURITY) as fh:
        raw = fh.read()
    lowered = raw.lower()
    assert "pip-audit" in lowered, "requirements-security.txt must declare pip-audit"
    assert "bandit" in lowered, "requirements-security.txt must declare bandit"
    # Each tool line must carry a version specifier (pinned, not floating).
    for tool in ("pip-audit", "bandit"):
        line = next(
            (ln for ln in lowered.splitlines() if ln.strip().startswith(tool)),
            None,
        )
        assert line is not None, f"no line for {tool}"
        assert any(op in line for op in ("==", ">=", "~=")), (
            f"{tool} is not version-pinned: {line!r}"
        )


def test_both_security_jobs_install_from_the_pinned_manifest():
    data = _pipeline()
    for job_name in SECURITY_JOBS:
        script = _all_script(data[job_name])
        assert "requirements-security.txt" in script, (
            f"{job_name}: must install tooling from requirements-security.txt"
        )


# --- no regression to the T52 gate -------------------------------------------

def test_offline_eval_gate_still_present_and_blocking():
    data = _pipeline()
    assert "eval:offline" in data
    offline = data["eval:offline"]
    assert offline.get("allow_failure") is not True
    for rule in offline.get("rules", []) or []:
        assert rule.get("when") != "manual"


def test_live_sweep_still_secret_scoped():
    with open(GITLAB_CI) as fh:
        raw = fh.read()
    data = yaml.safe_load(raw)
    assert "eval:live" in data
    assert "ANTHROPIC_API_KEY" in raw
