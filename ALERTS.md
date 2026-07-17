# Alert Definitions & On-Call Runbook — AI Clinical Co-Pilot

Alerts on top of the Braintrust dashboard (see `sidecar/DASHBOARD.md`). They read
the per-turn fields the sidecar logs to the `oe-ai-agent` Braintrust project
(`span.log(metrics=…, scores=…, metadata=…)` in `sidecar/server.py`, T38) plus the
`wrap_anthropic` call latency.

> **How these are created.** Braintrust alerts are **automations** configured in
> the UI (there is no public automation REST API — `/v1/automation` returns 404).
> Create each one from **Logs → filter → "Create alert from filters"** (or the
> Monitor page), paste the BTQL below, set the interval/window, and attach a
> notification target (**Slack channel or webhook**). The definitions here are the
> source of truth; the UI is just where they are instantiated. Thresholds are
> starting points — tune against observed baselines.

Dashboard: <https://www.braintrust.dev/app/KevinReynolds/p/oe-ai-agent/monitor>

Severity key: **P1** = page immediately; **P2** = notify on-call, respond same
shift; **P3** = informational / triage next business day.

---

## Alert 1 — p95 latency exceeding threshold  (P2)

| | |
|---|---|
| **Metric** | 95th percentile of agent-turn latency (dominated by the Anthropic call). Braintrust auto-records span **duration** on the `agent-turn` / `wrap_anthropic` spans — the exact BTQL field is the span duration metric Braintrust exposes (`duration`; confirm the unit/label in your Monitor view). |
| **Threshold** | **p95 > 10 s** sustained over a **15-minute** window |
| **BTQL** | `select percentile(duration, 0.95) as p95 from project_logs where created > now() - interval 15 minute` → alert when `p95` exceeds the 10 s threshold (match the unit Braintrust reports duration in) |
| **SQL filter** | `duration > 10` — the row-level slow-turn proxy for the p95 aggregate (alert when the *rate* of slow turns is high) |
| **Window / interval** | 15 min rolling, evaluated every 5 min |

**What it means.** One in twenty (or more) requests is slow enough that the
physician is left waiting — the core "answer in seconds, not minutes" promise
(`USER.md` §7) is breaking. The agent is read-only and the LLM call dominates
latency, so sustained high p95 almost always points outward (provider or network),
not at our own code.

**On-call response.**
1. Check `GET /ready` on the sidecar — is `llm` (Anthropic) reachable? Check the
   Anthropic status page.
2. On the dashboard, slice latency by time and look at token counts / cost per
   turn: a spike in input tokens (unusually large charts) vs. a flat token count
   with rising latency (provider-side slowness).
3. If provider-side and sustained: consider the documented fallback (a faster
   model) and post a status note to users; latency is a UX degradation, not an
   outage, so this is P2 not P1.
4. If token counts spiked: check for an unusually large patient chart or a
   context-assembly regression in a recent deploy; correlate with the deploy time.
5. Record the `correlation_id` of a slow turn from the logs to trace it end to end.

---

## Alert 2 — error rate exceeding threshold  (P1)

| | |
|---|---|
| **Metric** | Fraction of turns that failed outright (the turn returned the safe "assistant is unavailable" 502 / `scores.success = 0`, `metadata.outcome = "error"`) |
| **Threshold** | **error rate > 5 %** over a **15-minute** window (with a floor of ≥ 20 requests to avoid noise on low volume) |
| **BTQL** | `select count(*) filter (where scores.success = 0) / count(*) as error_rate from project_logs where created > now() - interval 15 minute` → alert when `error_rate > 0.05` |
| **SQL filter** | `scores.success = 0` — or `metadata.outcome = 'error'` (alert when > 5 % of events in the window match) |
| **Window / interval** | 15 min rolling, evaluated every 5 min |

**What it means.** More than 1 in 20 requests is failing completely — the agent
turn raised and was masked to a generic 502. Physicians are seeing "the assistant
is unavailable." This is a real outage of the feature; **P1**.

**On-call response.**
1. Check `GET /ready` — which dependency is down? `openemr` (boundary/DB), `llm`
   (Anthropic), or `observability`. `/ready` returns 503 and names the culprit.
2. Grep the sidecar logs for `agent turn failed cid=…` — every failure logs the
   `correlation_id`; pull one and trace it (the CID also lands in the OpenEMR
   audit log, T36).
3. Triage by cause:
   - **openemr down** → check the OpenEMR app + MySQL on Railway; the boundary
     read is failing.
   - **llm down** → Anthropic status; check the API key / quota.
   - **neither dep down (code bug)** → inspect the exception in the logs; if it
     started at a deploy boundary, **roll back the last sidecar deploy**.
4. Communicate: the feature is read-only and non-blocking, so clinicians fall back
   to reading the chart directly — note that in the incident channel.

---

## Alert 3 — tool failure rate exceeding threshold  (P2)

| | |
|---|---|
| **Metric** | Fraction of chart-tool executions that failed (`sum(metrics.tool_failures) / sum(metrics.tool_calls)`), i.e. boundary/`read.php` reads erroring mid-turn — the turns the agent marks **degraded** (T31) |
| **Threshold** | **tool failure rate > 10 %** over a **15-minute** window |
| **BTQL** | `select sum(metrics.tool_failures) / sum(metrics.tool_calls) as tool_fail_rate from project_logs where created > now() - interval 15 minute` → alert when `tool_fail_rate > 0.10` (cross-check `metadata.degraded = true` rate) |
| **SQL filter** | `metrics.tool_failures > 0` — or `metadata.degraded = true` (alert when > 10 % of turns in the window match) |
| **Window / interval** | 15 min rolling, evaluated every 5 min |

**What it means.** The agent is still answering, but its chart lookups are
frequently failing, so answers are silently thinning out and carrying the
"…may be incomplete" degraded disclosure (T31). This is a **data-quality /
partial-outage** signal, not a total failure — dangerous precisely because the
answers still look plausible. **P2**, escalate to P1 if it climbs toward the error
alert.

**On-call response.**
1. Check `GET /ready` `openemr` and hit `read.php`/`summary.php` on the OpenEMR app
   directly — are they 500-ing? Check MySQL and OpenEMR app health/logs.
2. On the dashboard, break tool failures down by tool (`metrics.tool_failures` with
   the per-tool `tool` events) to see if it's one tool (e.g. `search_chart` /
   `read.php`) or all — one tool points at a specific query/table; all points at
   the boundary or DB.
3. Correlate with recent OpenEMR-app deploys or a DB migration.
4. Pull a degraded turn's `correlation_id` and follow it to the failing boundary
   call in the OpenEMR audit log.
5. Until resolved, clinicians should treat agent answers as potentially
   incomplete — the degraded disclosure already tells them so, but flag it.

---

## Alert 4 — Verification-block rate exceeding threshold  (P2)

| | |
|---|---|
| **Metric** | Fraction of turns the verification gate **blocked** — replaced the draft with the safe fallback (`metadata.verification_verdict = 'blocked'`; V1/V2/V3/V6/V7, T24/T29) |
| **Threshold** | **block rate > 10 %** over a **1-hour** window (blocking is rare in normal operation) |
| **BTQL** | `select count(*) filter (where metadata.verification_verdict = 'blocked') / count(*) as block_rate from project_logs where created > now() - interval 1 hour` → alert when `block_rate > 0.10` |
| **SQL filter** | `metadata.verification_verdict = 'blocked'` (alert when > 10 % of turns in the window match) |
| **Window / interval** | 1 h rolling, evaluated every 15 min |

**What it means.** The safety gate is catching an unusual number of ungrounded,
misattributed, or contradictory drafts and withholding them (physicians get
"I can't verify that against the record"). The agent is **failing safe** — this is
not a data-exposure risk — but a rising block rate signals the model's grounding
is slipping: usually a system-prompt change (T33), a model-version change, or a
boundary payload-shape change that trips V3/V7.

**On-call response.**
1. Confirm it's genuine blocking, not a gate bug: pull a few blocked turns by
   `correlation_id`; read the draft vs. the raised flags
   (`contradicts_record` / `contradicts_status` / `out_of_scope_phi` / …).
2. Correlate with recent deploys — a prompt or model change is the usual cause; a
   boundary field-shape change can also trip the contradiction checks.
3. If a prompt/model regression: **roll back the sidecar deploy**.
4. If the gate is over-blocking legitimate answers (false positives): file a ticket
   to review the offending rule — **do NOT loosen the gate under incident pressure**
   without review; it is the trust boundary.
5. Fails safe, so **P2** (quality), not P1 (outage).

---

## Alert 5 — Truncation rate exceeding threshold  (P3 → P2)

| | |
|---|---|
| **Metric** | Fraction of turns that hit the tool-call budget and returned the "reached my lookup limit" partial answer (`metadata.truncated = true`; T30) |
| **Threshold** | **truncation rate > 15 %** over a **1-hour** window |
| **BTQL** | `select count(*) filter (where metadata.truncated = true) / count(*) as trunc_rate from project_logs where created > now() - interval 1 hour` → alert when `trunc_rate > 0.15` |
| **SQL filter** | `metadata.truncated = true` (alert when > 15 % of turns in the window match) |
| **Window / interval** | 1 h rolling, evaluated every 15 min |

**What it means.** Turns are frequently exhausting the max-tool-calls budget
(default 8) before the model finishes, forcing a partial answer with the
truncation disclosure. The answers are honest about being partial, but a high rate
means either the budget is too low for the real question complexity, or the model
is **looping** (over-calling tools) — either way physicians get incomplete answers
more often than they should.

**On-call response.**
1. Complexity vs. loop: pull truncated turns by `correlation_id`; look at
   `metrics.tool_calls` (all pinned at the cap?) and *which* tools ran — legitimate
   multi-source questions vs. the same tool repeatedly (a loop).
2. If genuine complexity: consider raising `OE_AI_AGENT_MAX_TOOL_CALLS` (env) — but
   weigh the latency/cost cost (more calls = slower, pricier); tune, don't crank.
3. If a loop (one tool repeatedly): a model/prompt regression — correlate with
   deploys and roll back if it started at a deploy boundary.
4. Cross-check the latency (Alert 1) and cost signals — loop-driven truncation
   usually shows up there too.
5. Normally **P3 / informational**; escalate to **P2** if truncation is high *and*
   answers are visibly degraded.

---

## Alert 6 — Extraction-failure rate exceeding threshold  (P2)

> **Week-2.** Derivable from the T57 structured events without Braintrust —
> `sidecar/alerts.py::evaluate_extraction_failure` decides it from the
> `panels.aggregate_week2_events` panel. The Braintrust definition below is for
> the dashboard view; the module is the in-process check.

| | |
|---|---|
| **Metric** | Fraction of intake-document extraction fields that did NOT land `ok` — the non-`ok` rate of the `extraction.field` outcome (T57). Each extracted field logs an `extraction.field` event whose `outcome` is `ok`, `unsupported`, or `low_confidence`; failure rate = `(total − ok) / total`. |
| **Threshold** | **extraction-failure rate > 20 %** (`0.20`) over a **1-hour** window, with a volume floor of **≥ 5 fields** (`min_fields`) to avoid noise on a single sparse document. A rate exactly equal to the threshold does NOT fire (strict `>`). |
| **BTQL** | `select count(*) filter (where metadata.outcome != 'ok') / count(*) as fail_rate from project_logs where metadata.event = 'extraction.field' and created > now() - interval 1 hour` → alert when `fail_rate > 0.20` and `count(*) >= 5` |
| **SQL filter** | `metadata.event = 'extraction.field' AND metadata.outcome != 'ok'` (alert when > 20 % of `extraction.field` events in the window match, given ≥ 5 total) |
| **Window / interval** | 1 h rolling, evaluated every 15 min |

**What it means.** The document-intake extractor is producing an unusual number
of `unsupported` / `low_confidence` fields instead of clean `ok` values — so
structured data pulled off intake forms is thinning out or degrading. Usually a
model/prompt regression in the extractor, a change in the incoming document
shape (a new form template, worse scans), or a boundary payload change. The
backing signal is the T57 `extraction.field` event and its `outcome`.

**On-call response.**
1. Pull a handful of recent non-`ok` `extraction.field` events by
   `correlation_id`; read `field` + `outcome` — is it one field type failing or
   many? One field points at a form/template change; many points at the
   extractor itself.
2. Check whether the failures cluster on a single document / template (a new
   intake form) vs. spread across all docs (a model/prompt regression).
3. If it started at a deploy boundary: **roll back the last sidecar deploy** — a
   prompt or model change to the extractor is the usual cause.
4. Verify the volume floor isn't masking a real spike the other way — a very low
   field count with 100 % failure is suppressed by design (`min_fields`), so
   check raw counts if intake volume is low.
5. Extraction is read-only and downstream consumers see the `outcome`, so this
   is a data-quality **P2**, not an outage.

---

## Alert 7 — RAG-retrieval latency exceeding threshold  (P2)

> **Week-2.** There is NO retrieval-latency field in the structured events, so —
> like Alert 1 — this is a Braintrust/BTQL span-duration definition. The
> DERIVABLE RAG-health complement is the retrieval HIT/MISS rate from the
> `retrieval.hit` / `retrieval.miss` events, surfaced by T59a in
> `panels.aggregate_week2_events` (`retrieval.hit_rate`).

| | |
|---|---|
| **Metric** | 95th percentile of the RAG retrieval span duration. Braintrust auto-records span **duration** on the retrieval span — the exact BTQL field is the span duration metric Braintrust exposes (`duration`; confirm the unit/label in your Monitor view), same shape as Alert 1's latency definition. |
| **Threshold** | **p95 retrieval duration > 2 s** sustained over a **15-minute** window |
| **BTQL** | `select percentile(duration, 0.95) as p95 from project_logs where span_attributes.name = 'retrieval' and created > now() - interval 15 minute` → alert when `p95` exceeds the 2 s threshold (match the unit Braintrust reports duration in) |
| **SQL filter** | `span_attributes.name = 'retrieval' AND duration > 2` — the row-level slow-retrieval proxy for the p95 aggregate |
| **Window / interval** | 15 min rolling, evaluated every 5 min |

**What it means.** Retrieval — the RAG lookup that grounds answers — is slow,
adding to overall turn latency (Alert 1) and pushing the "answer in seconds"
promise. Because there is no latency field in the T57 events, use the derivable
retrieval HIT/MISS rate (`retrieval.hit` / `retrieval.miss`, surfaced as
`retrieval.hit_rate` by T59a) as the complementary RAG-health signal: a falling
hit rate means the retriever is returning nothing useful (an index/embedding
problem), which often accompanies latency regressions.

**On-call response.**
1. On the dashboard, slice retrieval `duration` by time and confirm it's the
   retrieval span (not the LLM call, Alert 1) that regressed.
2. Check the derivable complement: is `retrieval.hit_rate` (from the T59a panel,
   `retrieval.hit` vs `retrieval.miss`) also dropping? Slow *and* missing points
   at the index/embedding store; slow but still hitting points at the store's
   latency/load.
3. Check the vector/index store health and its recent load; correlate with a
   re-index or embedding-model change.
4. If it started at a deploy boundary (retriever config, embedding model): roll
   back and re-measure.
5. Latency is UX degradation, not an outage, so **P2**; escalate if the hit rate
   collapse means answers are silently ungrounded.

---

## Alert 8 — Eval-regression (per-category pass-rate drop)  (P2)

> **Week-2.** DERIVABLE — `sidecar/alerts.py::detect_eval_regression` decides
> this from T59a's `by_category` eval breakdown. This is not a live-traffic
> Braintrust alert but a CI/offline check run against a stored baseline; mirrors
> `ci_gate.MAX_REGRESSION` semantics, keyed on category.

| | |
|---|---|
| **Metric** | Per-category eval pass rate from the T59a `by_category` breakdown (`eval.run_all` → `{category: {passed, total, pass_rate}}`). Compared against a stored baseline **per category**. |
| **Threshold** | Fires when **any category**'s pass rate drops by **MORE than 5%** (`0.05`) below baseline — `baseline_rate − current_rate > 0.05`, evaluated **per category**. A drop of EXACTLY 5% is allowed (strict `>`, mirroring `ci_gate.MAX_REGRESSION`). A category present in the baseline but absent from the current run is treated as a FULL drop (regression); a category present only in the current run is ignored. |
| **BTQL** | N/A — offline/CI check, not a live-traffic query. Compares the `by_category` summary from the current `eval.run_all` against the stored baseline summary. |
| **SQL filter** | N/A — see the `by_category` breakdown (T59a) as the backing signal; the decision is `detect_eval_regression(baseline_by_category, current_by_category)`. |
| **Window / interval** | Per eval run (CI, or scheduled offline run) against the recorded baseline |

**What it means.** A code, prompt, or model change has measurably degraded the
agent's answers for at least one clinical category (e.g. `diabetes`,
`hypertension`) — the per-category eval pass rate fell more than 5% below the
recorded baseline. Because it is per category, a broad-average gate could miss a
sharp drop in one category masked by gains elsewhere; this catches that. The
backing signal is the T59a `by_category` breakdown.

**On-call response.**
1. Identify which categories regressed (the sorted list `detect_eval_regression`
   returns) and by how much — compare `pass_rate` per category against baseline.
2. Inspect the newly-failing eval cases in those categories: read the actual vs.
   expected answers to see whether it's a real quality drop or a grader/fixture
   drift.
3. Correlate with recent changes — a system-prompt edit (T33), a model-version
   change, or a retrieval/context change is the usual cause; a missing category
   (full drop) often means an eval fixture was dropped, not a real regression.
4. If a genuine regression at a deploy/PR boundary: **block the merge / roll
   back** — the per-category gate exists to stop exactly this. Do NOT lower the
   baseline to make it pass without review.
5. If the "regression" is a baseline that's simply stale, refresh the baseline
   deliberately (reviewed), not under incident pressure. Quality gate, **P2**.

---

## Other signals (informational, not alerted by default)

- **Cost per hour** — `sum(metrics.cost_usd)` over 1 h vs. a budget line; catches a
  runaway loop or a token-size regression. Add as an alert if you set a cost budget.

## Notes

- All thresholds are **starting points** — set them from the observed baseline once
  real traffic accrues on the [dashboard](https://www.braintrust.dev/app/KevinReynolds/p/oe-ai-agent/monitor).
- The metric fields (`scores.success`, `metrics.tool_calls`, `metrics.tool_failures`,
  `metrics.cost_usd`, `metadata.verification_verdict`, `metadata.degraded`,
  `metadata.truncated`, `correlation_id`) are logged per turn by the sidecar (T38)
  — see `sidecar/DASHBOARD.md` for the full field mapping.
- Alerts only fire on data flowing from the **Railway** sidecar (Braintrust is not
  installed locally); a quiet dashboard means no production traffic, not that the
  alerts are broken.
