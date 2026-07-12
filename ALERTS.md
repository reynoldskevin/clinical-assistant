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
shift.

---

## Alert 1 — p95 latency exceeding threshold  (P2)

| | |
|---|---|
| **Metric** | 95th percentile of agent-turn latency (dominated by the Anthropic call). Braintrust auto-records span **duration** on the `agent-turn` / `wrap_anthropic` spans — the exact BTQL field is the span duration metric Braintrust exposes (`duration`; confirm the unit/label in your Monitor view). |
| **Threshold** | **p95 > 10 s** sustained over a **15-minute** window |
| **BTQL** | `select percentile(duration, 0.95) as p95 from project_logs where created > now() - interval 15 minute` → alert when `p95` exceeds the 10 s threshold (match the unit Braintrust reports duration in) |
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

## Agent-specific alerts (beyond the required three)

- **Verification-block rate** — `count(*) filter (where metadata.verification_verdict = 'blocked') / count(*)` over 1 h. A rising block rate (the gate replacing answers with the safe fallback) means the model is producing more ungrounded/contradictory drafts — a quality regression worth investigating (prompt or model change). **P2.**
- **Cost per hour** — `sum(metrics.cost_usd)` over 1 h vs. a budget line; catches a runaway loop or a token-size regression. **P2.**
- **Truncation rate** — `metadata.truncated = true` rate; a rising rate means turns are hitting the tool-call budget, hinting the budget is too low for real workloads. **P3 / informational.**

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
