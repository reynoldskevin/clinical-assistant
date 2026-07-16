---
id: 65
title: Golden-set depth — adversarial/extreme cases, broad diversity beyond templates
status: ready-for-merge
depends_on: [51]
branch: ticket/65-golden-set-depth
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_adversarial_set.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Depth deferred from T51. The T51 golden set is 50 cases generated from five
`template.format(i)` shapes, and its canonical `build_ideal_runner` "answers"
each case by pattern-matching a machine `[rubric:X]` tag embedded in the
question — so a template-era runner that never reads the natural-language body
still scores 100%. That set proves the pipeline is wired and the rubrics are
enforced, but it does not exercise adversarial or extreme inputs and carries
almost no lexical diversity. This ticket adds a second, deeper corpus that keeps
the exact same five boolean rubrics and their graders, but hardens breadth: a
hand-authored, template-free, adversarial/extreme case set that a template-era
runner provably cannot pass.

A new standalone `sidecar/adversarial_set.py` (the T51 `golden_set.py` stays
byte-for-byte, so its locked tests and the T52 CI gate are untouched):

1. **Adversarial/extreme, template-free corpus.** `load_adversarial_cases()`
   returns a hand-authored `AdversarialCase` list (≥30 cases, ≥3 per rubric),
   each carrying its `rubric`, an `attack` label naming the adversarial angle
   (jailbreak-roleplay, authority-override, obfuscated-injection, PHI-in-varied-
   form, contradictory-source, uncited-numeric, …), and a natural-language
   `question` that embeds NO `[rubric:X]` tag. The questions are diverse — no two
   share a normalized template stem — so they exercise the rubrics far beyond the
   five T51 shapes. The corpus reuses `golden_set.RUBRIC_GRADERS` verbatim (same
   rubric contract, deeper inputs).
2. **A reference oracle plus adversarial foils.** `build_adversarial_ideal_runner()`
   is an offline oracle whose crafted outputs satisfy every case (the set is
   satisfiable without an API key). Two foil runners prove the set has teeth
   beyond templates: `build_naive_template_runner()` (the T51 tag-matching runner)
   sees no tag, falls through, and fails the gate; `build_overcompliant_runner()`
   (a helpful-but-unsafe agent that always answers and never refuses) fails the
   safe-refusal rubric specifically. `run_adversarial_set(runner)` and
   `gate_adversarial_set(summary)` mirror the T51 API (same summary shape,
   per-rubric thresholds ≥ the golden thresholds; safe_refusal / no_phi_in_logs
   stay 1.0). The new locked test file runs in the sidecar suite, so the deeper
   set is enforced by CI by construction.

## Acceptance criteria
- [x] `load_adversarial_cases()` returns ≥30 unique-named, unique-question
  `AdversarialCase`s, ≥3 per rubric, every `rubric` in `golden_set.RUBRICS`, each
  with a non-empty `attack` label; the load is deterministic across calls.
- [x] No case question contains a `[rubric:` machine tag, and no two questions
  share a normalized template stem (digits/punctuation-stripped) — i.e. the set
  is diverse "beyond templates", unlike the T51 golden set.
- [x] The corpus reuses the golden rubric contract: `adversarial_set.RUBRIC_GRADERS
  is golden_set.RUBRIC_GRADERS`, and every case is gradable through the T51 eval
  harness `run_case` with the ideal runner.
- [x] `ADVERSARIAL_THRESHOLDS` covers exactly the five rubrics, each in `(0, 1]`
  and ≥ the corresponding `golden_set.THRESHOLDS`; `safe_refusal` and
  `no_phi_in_logs` are `1.0`.
- [x] `build_adversarial_ideal_runner()` passes every case (every rubric
  pass_rate `1.0`, `gate_adversarial_set` True).
- [x] Teeth: `build_naive_template_runner()` yields a pass_rate `< 1.0` with the
  gate False (the template-era runner cannot pass the deeper set); a blank runner
  also fails the gate.
- [x] The safety foil `build_overcompliant_runner()` drives `safe_refusal` below
  threshold and fails the gate (a helpful-but-unsafe agent is caught).
- [x] No regression: the T51 golden-set tests, the T52 CI-gate tests, and the
  full sidecar suite stay green; `golden_set.py` is unchanged.

## Test plan (orchestrator authors these)
- unit `sidecar/tests/test_adversarial_set.py`:
  - shape/diversity: ≥30 cases, unique names + questions, ≥3 per rubric, non-empty
    attack labels, ≥2 distinct attacks per rubric; no `[rubric:` tag; distinct
    normalized stems == case count; deterministic across loads.
  - contract reuse: `RUBRIC_GRADERS is golden_set.RUBRIC_GRADERS`; each case runs
    through `eval.run_case`; thresholds range + ≥ golden + safe/no_phi == 1.0.
  - satisfiability: ideal runner → every rubric 1.0, gate True.
  - teeth: naive template runner → pass_rate < 1.0 and gate False (safe_refusal &
    citation_present below threshold); blank runner → gate False.
  - safety foil: overcompliant runner → safe_refusal below threshold, gate False.
