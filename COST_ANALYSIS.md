# AI Cost Analysis — Clinical Co-Pilot

Actual dev spend, per-turn economics grounded in **measured** token usage, and
projected production cost at 100 / 1K / 10K / 100K users — with the architectural
changes each level forces. The headline: **cost is not `tokens × users`** — per-turn
cost is a variable you engineer down, and new cost *categories* appear as you scale.

## Measured unit economics (real turns)

Model: **`claude-opus-4-8`** — **$5 / 1M input**, **$25 / 1M output** tokens. Three
real turns against a data-rich patient (Brett333: 153 prescriptions, 88 encounters),
from the sidecar observability trace:

| Turn type | Model calls | Input tok | Output tok | Tool calls | **Cost** |
|---|---|---|---|---|---|
| Chart summary | 2 | 15,284 | 945 | 1 | **$0.100** |
| Focused Q&A (anticoagulant) | 2 | 18,013 | 459 | 1 | **$0.102** |
| Handoff draft | 3 | 89,388 | 1,780 | 9 (hit budget) | **$0.491** |

**Key fact: input tokens dominate.** Cost is driven by the *chart context* we send
(15K–90K input tok), not the answer (hundreds of output tok). A focused turn is
~$0.10; a many-tool synthesis is ~$0.50. Brett333 is an unusually heavy chart, so
these are toward the high end; a median ED patient is cheaper.

- **Blended working figure: ~$0.15 / turn** (naive — Opus, no caching, most turns
  focused with an occasional heavy synthesis).

## Actual dev spend (estimated)

_No direct billing-console access; estimated from observed usage. The unit tests
use scripted fakes ($0) — only real turns cost money._

| Item | Estimate | Basis |
|---|---|---|
| Anthropic API | **~$50–150** | A few hundred real turns over dev (the 80-turn load test ≈ $10–20, demos, live evals, ad-hoc testing) at ~$0.15–0.50 each |
| Railway hosting | **~$40–80** | 3 services (OpenEMR app, sidecar, MySQL) at ~$20–40/mo over ~1–2 months |
| Braintrust | **$0** | Free tier |
| **Total dev** | **~$100–250** | LLM dominates even in dev |

## Usage model (per active clinician)

From `USER.md`: ED attending, 8–10 h shifts, 2–3 new patients/hour, agent used at
~3 points per patient (context-gather, reassess, handoff). Estimate ~50 turns/shift
× ~20 shifts/month ≈ **~1,000 turns / active user / month**. "Users" below = *active
clinicians* (cost scales with turns, not registered accounts — a light specialty is
far cheaper per user than a high-tempo ED).

## Production cost projection

`LLM $/mo = users × 1,000 turns × $/turn`. **Naive** = Opus, no caching, $0.15/turn.
**Optimized** = prompt caching + model tiering + context trimming (see below),
~$0.04/turn (a ~75% reduction).

| Active users | Turns / mo | **Naive LLM/mo** | **Optimized LLM/mo** | Infra/mo (approx) | Dominant lever |
|---|---|---|---|---|---|
| **100** | 100K | **$15K** | **$4K** | ~$100 | turn on prompt caching |
| **1K** | 1M | **$150K** | **$40K** | ~$1–2K | caching + model tiering |
| **10K** | 10M | **$1.5M** | **$400K** | ~$10–20K | committed LLM capacity |
| **100K** | 100M | **$15M** | **~$4M** → less w/ enterprise commit | ~$100–300K | negotiated $/token; self-host cheap tier |

LLM cost dwarfs infrastructure at every level — so **the entire scaling strategy is
about driving $/turn down**, not about servers.

## Architectural changes required at each level

**100 users (~$4–15K/mo).** One sidecar, one Anthropic key on the standard tier,
one Postgres/MySQL. The one change that matters: **prompt caching** — the system
prompt, tool schemas, and the patient chart summary are identical across a
physician's several questions on the same patient, so cache the large input (reads
at ~0.1× input price). This alone cuts a multi-question patient session's cost
~60–70%. Infra is a rounding error.

**1K users (~$40–150K/mo).** Horizontal: several sidecar replicas behind a load
balancer, connection pooling to the boundary, boundary/DB **read replicas**.
Anthropic **rate limits** now bind → request a higher tier or shard across keys;
**prompt caching becomes mandatory**, not optional. Add **model tiering** — route
focused Q&A (the majority) to Sonnet/Haiku ($3/$15 or $1/$5), reserve Opus for
complex synthesis. Per-user **quotas / cost budgets** become a product feature.
Real PHI at this scale forces the **BAA + ZDR** path (M4) — a hard gate, not a cost
knob. Observability moves to a paid tier.

**10K users (~$400K–1.5M/mo).** **Committed/provisioned Anthropic throughput** (or
enterprise pricing) to escape per-request rate limits and get a better $/token.
**Aggressive caching**: a patient-summary cache invalidated on chart write (the
"who is this patient" answer is stable between edits), plus **context compression**
(the 90K-token handoff is wasteful — summarize/trim before sending; here the
*minimum-necessary* compliance work pays off financially). Autoscaling sidecar
fleet + a **queue with backpressure** to ride out provider throttling. Regional
deployment, cost-anomaly alerting, DB sharding. A distilled/fine-tuned smaller model
for the common query shapes starts to pencil out.

**100K users (~$4M+/mo).** Multi-region. The #1 lever is a **negotiated enterprise
LLM contract**; below it, **self-hosted open-weight models** for the cheap tier
(own GPU inference) become cheaper than API for high, steady volume — a
build-vs-buy inflection. **Semantic / answer caching**, heavy context compression,
per-tenant **fair-use rate limiting**. A real **data platform** for the audit +
disclosure logs (they grow with every turn), plus a dedicated **SRE/on-call + FinOps**
function. Engineering-org cost, not just infra cost, is now material.

## Why this is NOT `cost-per-token × n`

1. **$/turn is not constant** — it falls with architecture. Prompt caching, model
   tiering, and context trimming take the blended turn from ~$0.15 to ~$0.04, so
   naive linear scaling (**$15M at 100K**) overstates the real bill by ~4×.
2. **Input, not output, is the cost** — the chart context dominates, so the levers
   are all about *sending less / reusing more* (caching, trimming). The
   minimum-necessary design is a cost strategy as much as a compliance one.
3. **Infra is sublinear** (shared, autoscaled, cached) — but **new cost categories
   appear** at each tier that don't exist at 100 users: BAA/enterprise LLM commit,
   a compliance data platform, multi-region, an SRE org.
4. **Non-linear cliffs** change the architecture, not just the bill: Anthropic
   **rate limits** force capacity deals (1K→10K); **real PHI** forces BAA/ZDR (any
   real deployment); sustained volume flips the **build-vs-buy** math toward
   self-hosting the cheap tier (~100K).
5. **Usage intensity varies by user** — the ED is a worst case (high turns/shift);
   the same 100K users in a lower-tempo setting cost a fraction. Model the *turns*,
   not the head-count.

_Unit economics measured 2026-07 from the sidecar observability trace; dev spend and
infra are estimates (no billing-console access). Re-derive `$/turn` from the live
Braintrust cost metric (`metrics.cost_usd`, see `DASHBOARD.md`) as real traffic
accrues._
