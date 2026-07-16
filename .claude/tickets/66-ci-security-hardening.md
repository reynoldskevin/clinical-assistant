---
id: 66
title: CI hardening — dependency audit + security scan on every PR
status: tests-authored
depends_on: [52]
branch: ticket/66-ci-security-hardening
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_ci_security_gate.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Hardening deferred from T52 (the CI gate shipped happy-path: the offline eval
gate blocks merges on behavioural regressions, but nothing audits the sidecar's
dependency tree for known CVEs or scans its Python for insecure patterns). This
ticket adds a security tier to the GitLab pipeline: two new blocking, secret-free
jobs that run on every merge request and branch push, mirroring how `eval:offline`
is wired as a per-push blocking gate.

Two jobs in a new `security` stage of `.gitlab-ci.yml`, plus a pinned tooling
manifest so the scans are reproducible (matching the repo's pinned-deps ethos):

1. **Dependency audit (`security:deps`).** Runs `pip-audit` against the sidecar's
   `requirements.txt` / `requirements-dev.txt`, failing the pipeline when a
   declared dependency (or a resolved transitive) matches a known advisory. It is
   blocking (never `when: manual`, never `allow_failure: true`) and carries no
   secret (no `ANTHROPIC_API_KEY`), so it gates every PR.
2. **Static security scan (`security:scan`).** Runs `bandit` over the sidecar
   Python (excluding the test tree, whose `assert`-heavy cases are not production
   code) to catch insecure patterns (shell injection, weak crypto, hardcoded
   secrets, etc.). Also blocking and secret-free.

Both jobs install their tools from a pinned `sidecar/requirements-security.txt`
(`pip-audit` + `bandit`, version-pinned) so the audit is reproducible and cannot
silently float to a different tool version. The T52 `eval:offline` blocking gate
and `eval:live` scoped sweep are untouched. The tools are run against the current
tree during implementation so the jobs land green (any real finding is fixed by
pin/upgrade for deps, or fixed / documented-skip for bandit).

## Acceptance criteria
- [ ] `.gitlab-ci.yml` declares a `security` stage and two jobs, `security:deps`
  and `security:scan`, both assigned `stage: security`.
- [ ] Both security jobs are BLOCKING: no rule sets `when: manual`, and neither
  the job nor any rule sets `allow_failure: true`; they are not restricted to
  schedule/tag-only (they run on merge requests and branch pushes).
- [ ] Both security jobs are secret-free: no `ANTHROPIC_API_KEY` (or other secret)
  appears in the job definition.
- [ ] `security:deps` runs `pip-audit` against the sidecar requirements
  manifest(s); `security:scan` runs `bandit` over the sidecar source.
- [ ] A pinned `sidecar/requirements-security.txt` exists declaring both
  `pip-audit` and `bandit` with version specifiers, and both jobs install their
  tooling from it.
- [ ] The T52 gate is intact: `eval:offline` is still present and blocking and
  `eval:live` still carries the secret (no regression to the existing pipeline).
- [ ] The tools pass on the current tree (pip-audit reports no unresolved
  advisory; bandit reports no unaddressed finding), so the new jobs are green;
  the full sidecar pytest suite stays green.

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_ci_security_gate.py` (config-contract, offline — parses
  `.gitlab-ci.yml` + `requirements-security.txt`, mirrors the T52 GITLAB_CI style):
  - `security` stage declared; `security:deps` and `security:scan` exist with that
    stage.
  - each job blocking (no `when: manual`, no `allow_failure: true` at job or rule
    level) and not schedule/tag-restricted; secret-free (no `ANTHROPIC_API_KEY`).
  - `security:deps` script invokes `pip-audit` against `sidecar/requirements`;
    `security:scan` script invokes `bandit` over `sidecar`.
  - `sidecar/requirements-security.txt` pins `pip-audit` and `bandit`; both jobs
    install from it.
  - regression: `eval:offline` still present + blocking; `eval:live` still secret-scoped.
