# Cost & Latency Report — Clinical Co-Pilot (Week-2 MVP)

Actual dev spend, projected production cost, measured p50/p95 latency, and a
bottleneck analysis for the read-only AI Clinical Co-Pilot at the Week-2 MVP
milestone. Numbers are **measured**, not modelled: latency from live load tests
against the deployed sidecar, per-turn economics from the sidecar's own
observability traces.

> **Headline.** Production runs **Haiku 4.5**, not Opus. That single model-tier
> choice makes a real turn cost **~$0.016–0.02** and land in **~4–6 s** — a ~5×
> cost cut and ~2× latency cut versus the original Opus baseline. Cost is **not
> `tokens × users`**: `$/turn` is an engineered variable, **input tokens (chart
> context) dominate**, and new cost *categories* appear as you scale.

Companion docs (retained as detailed backing): [`COST_ANALYSIS.md`](COST_ANALYSIS.md)
(original Opus-era economics), [`METRICS_WEEK1.md`](METRICS_WEEK1.md) (single-user
latency baselines), [`STRESS_TESTS.md`](STRESS_TESTS.md) (concurrent load),
[`sidecar/DASHBOARD.md`](sidecar/DASHBOARD.md) / [`ALERTS.md`](ALERTS.md) (live
observability).

## What's new since Week 1 (and its cost/latency surface)

| W2 capability | Cost/latency impact |
|---|---|
| Document upload + **VLM extraction** (`/extract` → strict `LabFact`/`IntakeFact`) | One vision call per upload — a separate, one-off cost outside the `/ask` turn |
| **`get_intake_form`** tool (wires intake facts into `/ask`) | Runs the VLM extractor **on demand per intake question** — a per-turn cost + latency spike unless cached (see Findings) |
| **Hybrid RAG** `evidence_retriever` (BM25 + dense + Cohere rerank) | Adds a retrieval step + a small Cohere embed/rerank cost; a guideline turn is a second model call |
| **Citation gate + verification** | Extra output-token overhead (structured citations) + one gate pass; no extra model call |
| **Multi-turn conversation store** | Prior turns re-sent as input → input tokens grow across a session (caching target) |

## Methodology

- **Environment.** Live Railway deployment: sidecar `ai-sidecar-production-c492`
  (`python:3.12-slim`, `OE_AI_AGENT_MODEL=claude-haiku-4-5-20251001`), OpenEMR
  boundary `truthful-peace` over Railway's private network, Railway MySQL.
  Captured **2026-07-15**.
- **Latency** — `sidecar/perf/loadtest.py` (stdlib; nearest-rank percentiles)
  driving real end-to-end `/ask` turns (boundary read + tool loop + Claude call
  + verification gate). JWTs minted via the demo `dev_mint.php` endpoint (pid 1
  = Brett Cruickshank, a deliberately heavy chart).
- **Cost** — real per-turn `input_tokens`/`output_tokens` from the sidecar's
  observability trace (`agent turn: … trace={…}`), priced at Haiku 4.5 rates.
  Token counts are model-independent for the same prompt, so they are exact;
  only the price differs by tier.
- **Pricing.** Haiku 4.5 = **$1 / 1M input**, **$5 / 1M output**. Opus 4.8 (the
  original baseline) = $5 / $25. Unit tests use scripted fakes ($0) — only real
  turns cost money.

---

## 1. Actual dev spend

_No billing-console API access; estimated from observed usage. LLM dominates even
in dev; the bulk of the test suite (380 tests) runs on injected fakes at $0._

| Item | Estimate | Basis |
|---|---|---|
| Anthropic API | **~$60–160** | A few hundred real turns + VLM extractions over dev: load/stress batches, live evals (50-case golden set × iterations), demos, ad-hoc testing. Mostly Haiku (~$0.02/turn) with earlier Opus work (~$0.15/turn) |
| Railway hosting | **~$40–80** | 3 services (OpenEMR app, sidecar, MySQL) at ~$20–40/mo over ~1–2 months |
| Cohere (RAG rerank) | **~$0–5** | Free/near-free tier during dev |
| Braintrust (observability) | **$0** | Free tier |
| **Total dev** | **~$100–250** | LLM is the dominant line even in development |

---

## 2. Measured unit economics — live Haiku (real turns)

Three real turn types against the heavy demo chart, from the live observability
trace. **Input tokens dominate**: the cost is the *chart context we send*
(15K–80K in), not the answer (hundreds–low-thousands out).

| Turn type | Model calls | Tool calls | Input tok | Output tok | **Haiku cost** | _(same turn on Opus)_ |
|---|---|---|---|---|---|---|
| Chart summary | 2 | 1 | 14,565 | ~200 | **$0.0156** | _$0.100_ |
| Focused Q&A + guideline (RAG) | 2 | 2 | 17,817 | 589 | **$0.0208** | _$0.102_ |
| Full sign-out handoff | 3 | 8 | 81,124 | 2,791 | **$0.0951** | _$0.491_ |

- **Blended working figure: ~$0.02 / turn** (Haiku, no caching — most turns are
  focused, with an occasional heavy synthesis). ~7× cheaper than the Opus naive
  $0.15/turn.
- **VLM extraction** (`/extract`, per document upload): one vision call over the
  document image + ≤2,048 output tokens ≈ **$0.01–0.02** on Haiku — a one-off
  per-upload cost, not per-turn (but see Findings re `get_intake_form`).
- **RAG retrieval** adds a Cohere embed/rerank (fractions of a cent) + one extra
  model call, already included in the focused-RAG row above.

---

## 3. Latency — p50 / p95 (measured)

### Single-user (concurrency 1, live Haiku)

| Scenario | p50 | p95 | min / mean / max | Errors |
|---|---|---|---|---|
| Chart summary (`/ask`) | **4.4 s** | **6.5 s** | 3.5 / 4.6 / 6.5 s | 0 |
| Focused Q&A + guideline (RAG) | **5.5 s** | **7.5 s** | 5.0 / 5.8 / 7.5 s | 0 |
| _Opus baseline (Week 1, for reference)_ | _5.4 s_ | _12.5 s_ | _5.1 / 7.4 / — s_ | _0_ |

### Under concurrent load

| Concurrent users | p50 | p95 | p99 | Throughput | Errors |
|---|---|---|---|---|---|
| **10 in-flight** (Haiku, fresh) | **4.1 s** | **5.1 s** | 5.3 s | 2.2 req/s | **0 %** |
| _10 (Opus-era, `STRESS_TESTS.md`)_ | _5.8 s_ | _8.1 s_ | _11.5 s_ | _1.3 req/s_ | _0 %_ |
| _50 (Opus-era, `STRESS_TESTS.md`)_ | _8.9 s_ | _13.0 s_ | _15.5 s_ | _3.2 req/s_ | _0 %_ |

Haiku holds **p95 ~5 s even at 10 concurrent** with zero errors — well under the
`ALERTS.md` p95 > 10 s SLO. Degradation under load is graceful (queueing at the
provider, not the sidecar).

### Sidecar overhead is negligible (proves where time goes)

| Probe | p50 | p95 | Throughput |
|---|---|---|---|
| `GET /health` (no dependencies) | **1.1 ms** | **4.0 ms** | ~5,470 req/s |
| `GET /ready` (3 dependency reachability checks) | 937 ms | 1,190 ms | network-bound |

The process itself answers in ~1 ms at ~5.5k req/s; all real latency is in the
dependencies (the model call, and network round-trips).

---

## 4. Bottleneck analysis

**Latency bottleneck: the Claude model call (~90–95 % of a turn).**
- `/health` p50 = 1.1 ms proves the sidecar is thin; the OpenEMR boundary and
  Railway MySQL are ~0.4 s each; everything else is the LLM.
- The only real lever is **model tier** — already pulled: Haiku is ~2× faster
  than Opus in real turns and the dominant "make it faster" win. Sonnet was
  measured *slower* than Opus on real turns (verbose output), so it is not a
  latency win.
- Secondary lever: **input volume**. The 81K-token handoff is slower and costlier
  than a 15K-token summary — trimming context helps both axes.

**Cost bottleneck: input tokens (chart context), not output.**
- Every turn sends 15K–80K input tokens vs hundreds–low-thousands out. Levers are
  all about *sending less / reusing more*: **prompt caching** (the system prompt,
  tool schemas, and patient summary are identical across a clinician's several
  questions on one patient) and **context trimming**. Output-side optimization is
  a rounding error.
- The minimum-necessary design is a **cost** strategy as much as a compliance one.

**Under concurrency:** the bottleneck shifts to **provider queueing / rate
limits**, never the sidecar. Capacity planning is about Anthropic throughput, not
sidecar CPU/RSS (peak ~46 MB RSS, <15 % of one core on a turn).

---

## 5. Projected production cost

Usage model (from `USER.md`): an ED attending runs the agent at ~3 points per
patient × ~50 turns/shift × ~20 shifts/mo ≈ **~1,000 turns / active clinician /
month**. "Users" = *active clinicians* — cost scales with **turns**, not
registered accounts. `LLM $/mo = users × 1,000 turns × $/turn`.

- **Haiku, no caching** = measured **$0.02/turn**.
- **Optimized** = prompt caching (static ~14.5K chart+prompt reads at ~0.1×) +
  context trimming ≈ **~$0.01/turn** (~50 % cut; more on multi-question sessions).

| Active users | Turns / mo | **LLM/mo (Haiku)** | **LLM/mo (optimized)** | Infra/mo (approx) | Dominant lever |
|---|---|---|---|---|---|
| **100** | 100K | **~$2K** | **~$1K** | ~$100 | turn on prompt caching |
| **1K** | 1M | **~$20K** | **~$10K** | ~$1–2K | caching + rate-limit tier |
| **10K** | 10M | **~$200K** | **~$100K** | ~$10–20K | committed LLM capacity |
| **100K** | 100M | **~$2M** | **~$1M** | ~$100–300K | negotiated $/token; self-host cheap tier |

_For contrast, the original all-Opus naive projection was $15K → $15M across the
same tiers. Choosing Haiku as the production tier already bought a ~7× reduction —
before any caching._

LLM cost dwarfs infrastructure at every level, so **the scaling strategy is about
driving `$/turn` down**, not about servers.

## 6. Architectural changes required at each level

**100 users (~$1–2K/mo).** One sidecar, one Anthropic key on the standard tier,
one MySQL. The change that matters: **prompt caching** — cache the large, stable
input (system prompt, tool schemas, patient summary) across a clinician's several
questions on one patient. Infra is a rounding error.

**1K users (~$10–20K/mo).** Horizontal: several sidecar replicas behind a load
balancer, connection pooling, boundary/DB **read replicas**. Anthropic **rate
limits** now bind → higher tier or shard across keys; **caching becomes
mandatory**. Keep **model tiering** deliberate (Haiku default; escalate only the
genuinely-complex synthesis). Per-user **quotas / cost budgets** become a product
feature. Real PHI forces the **BAA + ZDR** path (M4) — a hard gate, not a cost
knob. Observability moves to a paid tier.

**10K users (~$100–200K/mo).** **Committed/provisioned Anthropic throughput** (or
enterprise pricing) to escape per-request limits and improve $/token. **Aggressive
caching**: a patient-summary cache invalidated on chart write, plus **context
compression** (trim the 80K-token handoff before sending). **Cache extraction
results** so `get_intake_form` doesn't re-run the VLM per question. Autoscaling
fleet + a **queue with backpressure** for provider throttling; regional deploy;
cost-anomaly alerting; DB sharding.

**100K users (~$1–2M/mo).** Multi-region. The #1 lever is a **negotiated
enterprise LLM contract**; below it, **self-hosted open-weight models** for the
cheap tier become cheaper than API at high, steady volume (a build-vs-buy
inflection). **Semantic / answer caching**, heavy context compression, per-tenant
fair-use limits. A real **data platform** for the audit + disclosure logs (they
grow every turn), plus a dedicated **SRE/on-call + FinOps** function.

## 7. Why this is NOT `cost-per-token × n`

1. **`$/turn` is not constant** — it falls with architecture. Model tiering
   (Opus→Haiku) already took the turn from ~$0.15 to ~$0.02; caching + trimming
   take it to ~$0.01. Naive linear scaling overstates the real bill several-fold.
2. **Input, not output, is the cost** — chart context dominates, so every lever is
   *send less / reuse more* (caching, trimming). Minimum-necessary is a cost lever.
3. **Infra is sublinear** (shared, autoscaled, cached), but **new cost categories
   appear** at each tier that don't exist at 100 users: BAA/enterprise commit, a
   compliance data platform, multi-region, an SRE org.
4. **Non-linear cliffs** change the architecture, not just the bill: Anthropic
   **rate limits** force capacity deals (1K→10K); **real PHI** forces BAA/ZDR
   (any real deployment); sustained volume flips **build-vs-buy** toward
   self-hosting the cheap tier (~100K).
5. **Usage intensity varies by user** — the ED is a worst case; the same head-count
   in a lower-tempo setting costs a fraction. Model the *turns*, not the accounts.

## 8. Findings / action items surfaced by this measurement

1. **Dashboard `cost_usd` is mispriced for Haiku (overstates ~5×).**
   `sidecar/observability.py` `_PRICING` has only a `claude-opus-4-8` entry, and
   `default_agent_builder` constructs `TraceCollector()` **without** the configured
   model — so every live Haiku turn logs Opus-priced cost (e.g. a $0.0156 turn
   logs as ~$0.078). Fix: add Haiku 4.5 (`$1/$5`) to `_PRICING` and pass the
   configured model into `TraceCollector(model=...)`. Low-risk, high-value.
2. **`get_intake_form` re-runs the VLM extractor per intake question.** Fine at MVP
   volume, but at scale it adds a per-turn vision cost + latency spike. Cache the
   `/extract` result (server-side keyed by pid/document) and read the cache first —
   the natural "Option 2" follow-up to the intake-facts fix.
3. **Context trimming is the next cost/latency win.** The 81K-token handoff is 5×
   the cost and materially slower than a focused turn; summarize/trim chart context
   before sending on the heavy synthesis path.

_Latency captured 2026-07-15 via `sidecar/perf/loadtest.py` against the live
Railway Haiku sidecar; per-turn tokens from the live observability trace, priced
at Haiku 4.5 rates. Re-derive `$/turn` from the Braintrust `metrics.cost_usd`
(after fix #8.1) as real traffic accrues._
