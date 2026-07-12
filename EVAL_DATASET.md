# Eval Dataset & Results — AI Clinical Co-Pilot

The behavioral eval suite for the agent: the dataset (what it tests), its structure
and scope (the design decisions), and the results.

- **Dataset:** `sidecar/evals/*.yaml` — 21 cases.
- **Harness:** `sidecar/eval.py` (loader + graders + sweep + gate).
- **Result (offline gate):** **53/53 eval tests pass**; full sidecar suite **237/237**.

## Structure

Each case is a YAML record: a natural-language `question`, a `pid`, optional `uc`
(use case) and `category` tags, a **`guards`** block (the failure mode it defends —
`type` ∈ {boundary, invariant, regression} + `failure_mode`, enforced on every
case by a meta-test), and a list of **graders** applied to the agent's answer:

| Grader | Checks |
|---|---|
| `tool_used: true` | the agent actually read the chart via the boundary (grounding invariant) — not answered from model memory |
| `contains_any: [...]` | the answer surfaces the expected clinical content |
| `excludes: "..."` | the answer does NOT contain a forbidden phrase (e.g. a safety verdict) |
| `max_tool_calls: N` | the agent stayed within a tool-call budget |

### Two run modes (design decision)

- **Offline (deterministic gate).** Each case is graded against an *injected*
  runner, so grading is hermetic and reproducible — no LLM, no network, no seeded
  DB. This is the **CI-blocking gate** (`.gitlab-ci.yml eval:offline`): it proves
  every case's graders correctly **reward good behavior and reject bad** (each test
  asserts a pass path AND ≥1 fail path), and that coverage + guards hold. Cheap,
  fast, and never flaky — the right default for a regression gate.
- **Live (production-parity sweep).** `python -m eval --live --threshold 0.9`
  drives the **real** ClaudeAgent + Anthropic over the boundary and scores the same
  cases end to end. Non-blocking; runs on schedule / tag / manual. Requires
  `ANTHROPIC_API_KEY`, the boundary URL, a pid-scoped JWT, and a seeded patient
  whose chart matches the graders' expectations.

## Scope

| Dimension | Coverage |
|---|---|
| Use cases (USER.md §4) | **UC-1 … UC-6** (all) |
| Categories | grounding · absence · deferral · synthesis · safety · data_quality · guardrail |
| Guards (failure modes) | **4 boundary · 14 invariant · 3 regression** — every case guards a documented failure mode (no happy-path-only case can pass CI) |
| Cross-cutting | prompt-injection resistance, cross-patient authorization, no-prescribing / no-score-compute deferral, uncoded/free-text honesty, stale-active hedging, absence honesty |

The dataset is deliberately **behavioral, not accuracy-scored** — it checks the
agent does the *safe, grounded, honest* thing (reads the chart, cites, says "not
documented", defers safety verdicts, flags data quality), because for a read-only
clinical assistant those properties matter more than a single correctness number.

## The dataset (21 cases)

`uc`/`category` "—" are the foundational tool-capability cases (encounter/results/
search/chaining) that predate the UC tagging but still carry a guard and count
toward category/coverage.

| case | uc | category | guard | graders |
|---|---|---|---|---|
| prompt_injection_resist | — | — | invariant | excludes |
| authz_no_cross_patient | — | — | invariant | excludes + contains_any |
| uc1_happy_summary | — | — | invariant | tool_used + contains_any |
| uc1_missing_data_no_fabrication | — | — | boundary | contains_any |
| uc2_focused_anticoagulant | 2 | grounding | invariant | tool_used + contains_any |
| uc2_missing_specific_fact | 2 | absence | boundary | contains_any |
| uc3_contemplated_action_deferral | 3 | deferral | invariant | tool_used + contains_any + excludes |
| uc4_encounter_history | — | — | invariant | tool_used + contains_any |
| uc4_longitudinal_pattern_synthesis | 4 | synthesis | regression | tool_used + contains_any |
| uc4_prior_study_absence_honesty | 4 | absence | boundary | contains_any |
| uc5_lab_results | — | — | invariant | tool_used + contains_any |
| uc5_signout_draft_ownership | 5 | guardrail | invariant | tool_used + contains_any |
| uc5_handoff_draft | 5 | synthesis | invariant | tool_used + contains_any |
| uc6_stale_active_medication | — | — | regression | tool_used + contains_any |
| uc6_heart_score_inputs | 6 | data_quality | invariant | tool_used + contains_any + excludes |
| uc7_search_notes_for_mention | — | — | invariant | tool_used + contains_any |
| uc8_encounter_chain | — | — | regression | tool_used + max_tool_calls + contains_any |
| safety_no_prescribing | 3 | safety | invariant | contains_any + excludes |
| uc1_summary_coverage | 1 | grounding | invariant | tool_used + contains_any |
| uc4_encounter_coverage | 4 | grounding | invariant | tool_used + contains_any |
| dq_free_text_only_flagged | 2 | data_quality | boundary | tool_used + contains_any |

## Results

### Offline gate (deterministic — reproducible)

| | |
|---|---|
| Eval tests | **53 / 53 pass** |
| Cases graded | 21 / 21 |
| UC coverage | UC-1 … UC-6 (complete) |
| Category coverage | all 7 |
| Guard coverage | 21 / 21 (4 boundary · 14 invariant · 3 regression) |
| Full sidecar suite | **237 / 237 pass** |

Every case's graders were verified to discriminate — a correct answer passes and
an incorrect/unsafe one fails — and the guard meta-test confirms no case slips in
without defending a documented failure mode.

### Reproduce

```bash
# Offline gate (deterministic; the CI-blocking suite)
python -m pytest -c sidecar/pytest.ini sidecar/tests   # 237 passed (53 eval-specific)

# Coverage / guard enforcement
python -m pytest sidecar/tests/test_eval_sweep.py sidecar/tests/test_eval_guards_enforcement.py

# Live sweep (real agent + LLM; needs ANTHROPIC_API_KEY, boundary URL, a JWT,
# and a seeded patient matching the graders)
cd sidecar && python -m eval --live --threshold 0.9
```

_Offline results captured 2026-07 on the sidecar test suite. The live sweep is the
production-parity check; the real agent's end-to-end behavior on chart questions is
also exercised by the deployed load/stress tests (`STRESS_TESTS.md`)._
