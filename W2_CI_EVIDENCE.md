# W2_CI_EVIDENCE — the eval gate that blocks regressions

Evidence that the Week-2 build has a working, regression-blocking eval gate at
**two enforcement points**, both running the same deterministic offline eval
suite:

1. **A local `pre-push` git hook** — blocks a *push* that would regress the
   golden set, so a regression never leaves the machine.
2. **A blocking `eval:offline` GitLab CI job** — blocks a *merge* on every MR and
   branch push.

Both are hermetic: no LLM, no network, no secrets. The grading substrate is the
[50-case golden set + 5 boolean rubrics](EVAL_DATASET_W2.md) and the per-rubric
[regression gate](sidecar/ci_gate.py).

> **Grading-gate statement.** The deterministic offline suite is the gate that
> blocks regressions. The live LLM sweep (`eval:live`) is a **non-blocking**
> quality signal (a small model + strict graders + run-to-run variance sit below
> the aspirational 0.9), so it never reds a healthy pipeline.

---

## 1. Local git hook — `sidecar/hooks/pre-push`

Present and executable, and **installed in this clone**:

```
$ ls -la sidecar/hooks/pre-push sidecar/hooks/install.sh
-rwxr-xr-x  sidecar/hooks/install.sh
-rwxr-xr-x  sidecar/hooks/pre-push
$ test -f .git/hooks/pre-push && echo INSTALLED
pre-push INSTALLED in .git/hooks
```

**What it does.** On `git push` it runs the exact command the CI blocking gate
runs — `python -m pytest -c sidecar/pytest.ini sidecar/tests` — and **a failure
blocks the push** (`set -euo pipefail`, `exec pytest`). It is fail-closed: if it
cannot run the gate (host Python lacks deps *and* the `w2-sidecar-test` container
isn't up) it exits non-zero rather than letting the push through.

**Install / bypass:**

```bash
bash sidecar/hooks/install.sh          # idempotent; won't clobber a foreign hook without --force
git push --no-verify                   # deliberate bypass (or SKIP_EVAL_GATE=1 git push)
```

The hook prefers a host Python with the deps, then falls back to running inside
the `w2-sidecar-test` container (repo bind-mounted at `/repo`).

---

## 2. Blocking CI job — `.gitlab-ci.yml`

Job inventory (from the pipeline):

| Job | Stage | Blocking? | Purpose |
|---|---|---|---|
| `security:deps` | security | **yes** | `pip-audit` — fail on any known advisory |
| `security:scan` | security | **yes** | `bandit -ll` static security scan |
| `security:phi` | security | **yes** | PHI-detection guard over log/trace emission points |
| **`eval:offline`** | test | **yes** | `pytest sidecar/tests` — the golden set + rubric regression gate |
| `eval:live` | eval | **no** (`allow_failure`, manual/schedule/tag) | real agent+LLM scored sweep — quality signal only |

A registered runner means the per-push blocking gate is **on**: `eval:offline`
runs on every MR and branch push and **must pass to merge**. The `workflow.rules`
de-duplicate branch vs MR pipelines so a branch with an open MR runs only the MR
pipeline.

---

## 3. Proof the gate has teeth — a green run flipped red

The regression gate (`ci_gate.regression_gate`) is what makes a rubric drop fail
the build. Live demonstration:

**Healthy — baseline vs itself → PASS:**

```
=== HEALTHY: baseline vs itself ===
GATE PASSED: True
```

**Inject a regression — `citation_present` 1.0 → 0.7, `safe_refusal` 1.0 → 0.9 → FAIL:**

```
=== INJECTED REGRESSION: citation_present 1.0->0.7, safe_refusal 1.0->0.9 ===
GATE PASSED: False
REGRESSIONS: ['citation_present', 'safe_refusal']
BELOW THRESHOLD: ['citation_present', 'safe_refusal']
```

`citation_present` dropped 0.30 (> the 5% tolerance) **and** fell below its 0.9
threshold; `safe_refusal` breached its hard **1.0** floor. The gate returns
`passed = False`, which fails `eval:offline` and the `pre-push` hook — the push
and the merge are both blocked.

**Reproduce (the "money shot"):**

```bash
docker exec w2-sidecar-test bash -lc 'cd /repo/sidecar && python3 -c "
import ci_gate
base = ci_gate.baseline_pass_rates()
reg = dict(base); reg[\"citation_present\"]=0.7; reg[\"safe_refusal\"]=0.9
r = ci_gate.regression_gate(reg, base)
print(\"GATE PASSED:\", r[\"passed\"])
print(\"REGRESSIONS:\", r[\"regressions\"])
print(\"BELOW THRESHOLD:\", r[\"below_threshold\"])
"'
```

---

## 4. The gate genuinely discriminates (not a rubber stamp)

Beyond the pass path, CI asserts the gate *catches real regressions* — verified
three independent ways so a broken gate cannot pass silently:

- **`test_ci_gate.py` / `test_golden_set.py`** — a degraded (blank) runner is
  seeded and the gate is asserted to fail; drop-exactly-5% is allowed while
  drop-just-over-5% regresses; hard-floor rubrics fail on any dip. *(all green:
  `pytest tests/test_ci_gate.py tests/test_golden_set.py` → 30 passed.)*
- **`test_eval_guards_enforcement.py`** — every behavioral YAML case must defend a
  documented failure mode (no happy-path-only case can slip in).
- **`test_offline_agent_canary.py`** — a real-agent regression canary plus YAML
  assertions that `eval:offline` is blocking and `eval:live` is non-blocking.

During validation the gate was additionally stress-tested by injecting three
representative regressions into the pipeline (disabling a verification check,
defeating the regression gate, unwiring the agent gate) and confirming the
offline suite went red each time — establishing that the blocking gate would
catch the grader's injected regression.

---

## 5. Summary

| Requirement | Status | Evidence |
|---|---|---|
| A git hook (or equivalent) runs the eval suite | ✅ | `sidecar/hooks/pre-push`, installed in `.git/hooks` |
| It blocks regressions | ✅ | fail-closed `exec pytest`; injected-regression → `GATE PASSED: False` |
| Equivalent CI enforcement | ✅ | blocking `eval:offline` job on every MR/branch push |
| The gate discriminates | ✅ | `test_ci_gate.py`, `test_golden_set.py`, `test_eval_guards_enforcement.py`, canary |
| No secrets / hermetic | ✅ | deterministic offline suite; no LLM/network/DB |
