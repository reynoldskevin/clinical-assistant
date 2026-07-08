# Target User & Use Cases — Emergency Physician

---

## 1. Persona: Dr. Smith, ED Attending Physician

- **Role:** Board-certified emergency physician (FACEP), works attending shifts in a mixed community/academic Emergency Department.
- **Shift shape:** 8–10 hour shifts, ~2–3 new patients/hour, **8–15 active patients in parallel**, constant interruptions (nurses, consultants, EMS, critical alerts). Cognitive load and context-switching are the defining constraints.
- **Core reality of EM:** *undifferentiated, time-critical patients, usually with little-to-no prior context in hand.* Decisions are made on incomplete information, fast, with high stakes.
- **Tech context:** Uses OpenEMR at a shared workstation and on a mobile cart; documents between patients; relies heavily on prior records when they exist but rarely has time to read them thoroughly.
- **What he values:** speed, trust/verifiability, and *not missing something* — a prior aortic aneurysm, an anticoagulant, a recent identical workup. He will not use a tool that is slow, that he can't verify, or that cries wolf.

---

## 2. The ED encounter workflow (where the agent fits)

```
EMS/triage → [CONTEXT-GATHER] → focused H&P/exam → workup (labs/imaging) → [REASSESS] → disposition (admit/discharge/transfer) → [DOCUMENT/HANDOFF]
```

The agent is a **read-only synthesis layer** at three high-value, low-risk points — it never orders, prescribes, or writes to the chart:

- **CONTEXT-GATHER** (before/at first contact): "who is this person, medically?"
- **REASSESS** (mid-workup, per new question): focused Q&A over the chart.
- **DOCUMENT/HANDOFF** (end of involvement/shift): draft summaries the physician verifies.

These are exactly the moments an ED doctor is **information-starved and time-poor** — the sweet spot for read-only assistance.

---

## 3. Goals & pain points the agent targets

| Pain point | Impact in the ED |
|---|---|
| Prior records are long, scattered, mostly **free text**, and rarely read under time pressure | Missed history; repeated workups; anchoring errors |
| Answering one specific question ("is she anticoagulated?") means clicking through tabs | Minutes lost per patient × 10+ patients |
| Records are **incomplete/inconsistent** (per the data-quality audit: uncoded problems, missing fields, duplicate patients) | Structured views under-report; the truth is in the narrative |
| Handoffs and chart review are cognitively expensive and error-prone at shift change | Continuity/safety risk |

---

## 4. Use cases

Each use case: **Scenario → What the agent does → Why an agent is the right solution → Guardrails.**

### UC-1 — Rapid prior-history synthesis ("who is this patient, medically?")
- **Scenario:** A 68-year-old arrives with chest pain. Dr. Chen has 60 seconds before walking in.
- **What the agent does:** Produces a focused, ED-relevant snapshot from the entire chart — active problems, current meds, allergies, recent encounters, pertinent prior events (e.g., prior MI, stents, aneurysm), and relevant recent results — *weighted to the presenting complaint*.
- **Why an agent is the right solution:** The task is **open-ended synthesis over heterogeneous, largely free-text data**, where *what counts as relevant changes with every presentation*. A static summary page or report can't anticipate "relevant to chest pain today"; keyword search can't read a discharge summary and extract "had a drug-eluting stent in 2023." Only a language model can compress a sprawling narrative into a complaint-focused brief on demand. This is the canonical agent job: **variable intent + unstructured input + time pressure.**
- **Guardrails:** Read-only; every claim links to its source note/result; surfaces "not found in record" explicitly; flags data-quality gaps (see §6).

### UC-2 — Focused clinical Q&A over the chart
- **Scenario:** Mid-workup, Dr. Chen needs specific facts fast: *"Has she ever had a troponin, and what was the trend?"* … *"Is he on an anticoagulant or antiplatelet?"* … *"Any prior CT of the abdomen and what did it show?"*
- **What the agent does:** Answers the natural-language question grounded strictly in this patient's record, with the supporting values/notes cited.
- **Why an agent is the right solution:** The questions are **ad hoc and unpredictable** — you cannot pre-build a report or dashboard tile for every question a physician might ask. Natural language is **faster than navigating the UI** when your hands are gloved and the patient is in front of you, and many answers require **reading and interpreting free-text notes** (e.g., "the CT showed a 4 cm AAA"), which structured queries can't do. An agent turns "10 clicks across 4 tabs" into one spoken question.
- **Guardrails:** Answers only from the record; says "not documented" rather than guessing; shows the exact source for verification.

### UC-3 — Patient-specific context for a contemplated action
- **Scenario:** Dr. Chen considers contrast CT / ketorolac / a sedative and asks *"anything about this patient I should factor in?"*
- **What the agent does:** Surfaces the **patient-specific** context that bears on the decision — relevant allergies, current meds, recent renal function, prior reactions, pregnancy status if documented — as a narrative with sources.
- **Why an agent is the right solution:** The value is **assembling scattered, patient-specific facts** (a creatinine buried in last month's labs + an ACE-inhibitor on the med list + a contrast-allergy note in free text) into one relevant picture — synthesis a fixed alert can't personalize and a search box can't correlate. **Important honesty:** the agent is *not* the drug-interaction database or the dosing calculator — those must stay **deterministic tools** (see §5). The agent's job is patient-context synthesis and *pointing at* the hard checks, not performing them.
- **Guardrails:** Framed as decision-*support*, not a recommendation; defers interaction/dose logic to deterministic engines; cites every fact.

### UC-4 — Longitudinal / "frequent-utilizer" pattern surfacing
- **Scenario:** A patient with 9 prior ED visits presents again with abdominal pain. *"Has he been worked up for this before — what was found and done?"*
- **What the agent does:** Summarizes the relevant prior encounters into a pattern: what was investigated, what imaging/labs were already done, what the diagnoses/dispositions were.
- **Why an agent is the right solution:** A deterministic query can *count* visits and list dates; it **cannot read ten free-text narratives and tell the story** of "already had three negative CTs for this same pain." Avoiding a redundant scan or catching an evolving pattern requires **narrative synthesis across many documents** — precisely what an LLM does and rules/reports do not. Also directly reduces cost and radiation from repeat workups.
- **Guardrails:** Read-only; cites each prior encounter; explicit about visits it could/couldn't retrieve.

### UC-5 — Handoff / sign-out draft at shift change
- **Scenario:** End of shift; Dr. Chen must hand off 7 active patients.
- **What the agent does:** Drafts a concise per-patient ED-course summary (presentation → workup so far → pending results → current thinking) from the chart, for the physician to verify and deliver.
- **Why an agent is the right solution:** A handoff is an **unstructured narrative that varies per patient** — no template can write "68F chest pain, troponin pending, low HEART, likely dischargeable if second trop negative." Producing it requires **reading the evolving record and composing prose**, the core LLM capability. It reclaims the most cognitively expensive, safety-critical few minutes of the shift.
- **Guardrails:** **Draft only** — the physician edits and owns it (agent is read-only, no chart write-back yet); pending/uncertain items flagged, not invented.

### UC-6 — Assembling inputs for a risk score / pathway
- **Scenario:** Dr. Chen is applying HEART / PERC / a sepsis pathway and needs the input data. *"Pull the elements for a HEART score on this patient."*
- **What the agent does:** Extracts the required data elements from structured fields **and free text** (age, risk factors, prior events, relevant vitals/labs) and presents them for the physician to apply.
- **Why an agent is the right solution:** The *hard part* is **finding scattered inputs across coded fields and narrative** ("diabetic" mentioned only in a note; a prior positive stress test in a 2024 letter). Gathering those is synthesis; an agent excels at it. **The score itself is computed deterministically** — the agent assembles and explains inputs, it does not replace the validated calculator.
- **Guardrails:** Shows each input's source; the physician confirms; scoring math stays in a deterministic tool.

---

## 5. When an agent is NOT the right solution (explicit non-goals)

Stating these sharpens *why* the above are agent-appropriate — and keeps the agent away from where it would be unsafe or worse than existing tools:

- **Exact calculations** (drug doses, weight-based peds dosing, infusion rates) → deterministic calculators. Never the LLM.
- **Drug–drug / drug–allergy interaction checking** → a maintained interaction database with complete, current rules. The agent *surfaces context and points* to it (UC-3), it isn't the source of truth.
- **Hard-stop safety alerts / clinical decision rules** (critical-value alerts, allergy hard stops) → deterministic, must-fire-every-time rules. Agents are probabilistic; safety-critical alerting cannot be.
- **Deterministic lookups** ("show today's CBC") → the existing UI/report is faster and exact.
- **Anything requiring a write** (orders, prescriptions, documentation into the legal record) → out of scope for the read-only agent; would demand write-path audit, clinical-safety review, and likely a BAA-gated production posture.

**Rule of thumb:** the agent is right when the task is **open-ended natural-language synthesis over heterogeneous, mostly free-text patient data with per-patient-variable intent, under time pressure** — and wrong when the task needs **exactness, completeness guarantees, or a state change.**

---

## 6. Data-reality caveats the agent must handle.

ED records are especially messy; the agent must degrade gracefully and never paper over gaps:

- **Uncoded / free-text problems & meds** are common — the agent must read the narrative, not just the coded lists, and say when data is free-text-only.
- **Missing fields** (`empty ≠ absent`) — the agent must say "not documented," never infer a negative.
- **Duplicate patient records** exist (no natural-key uniqueness) — the agent should flag possible duplicate/merge candidates rather than silently miss a chart split across two `pid`s.
- **Stale "active" flags** (resolved problems still marked active) — surface status *and* dates so the physician judges currency.

---

## 7. What "good" looks like (success criteria)

- **Fast:** useful answer within the real-time budget (the LLM call dominates; context assembly must be cheap).
- **Verifiable:** every clinical claim cites its source in the chart; one click to the underlying note/result.
- **Honest about gaps:** "not documented," "free-text only," "possible duplicate chart" — no fabrication, no false negatives asserted as fact.
- **Trusted:** Dr. Chen would rely on it to *point her at* the right part of the record — and independently verify before acting.
