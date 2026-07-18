# Cost & Latency Report — Clinical Co-Pilot (Week 2, FINAL)

Actual dev spend, projected production cost, measured **p50/p95** latency, and a
bottleneck analysis for the read-only AI Clinical Co-Pilot at the end of Week 2,
with all four Week-2 capabilities shipped (document ingestion + VLM extraction,
hybrid RAG, supervisor/worker graph, eval-gated CI) and Qdrant + per-tool
observability live on Railway.

Numbers are **measured**, not modelled: latency from live load tests against the
deployed sidecar; per-turn economics from the sidecar's own observability traces.

> **Headline.** Production runs **Haiku 4.5**, not Opus. That single model-tier
> choice makes a real turn cost **~$0.016–0.02** and land in **~4–6 s** — a ~5×
> cost cut and ~2× latency cut vs. the original Opus baseline. Cost is **not
> `tokens × users`**: `$/turn` is an *engineered* variable, **input tokens
> (chart context) dominate**, and new cost *categories* appear as you scale.

Backing detail: [`COST_ANALYSIS_W2_MVP.md`](COST_ANALYSIS_W2_MVP.md) (the full MVP
measurement writeup), [`COST_ANALYSIS.md`](COST_ANALYSIS.md) (Opus-era baseline),
[`METRICS_WEEK1.md`](METRICS_WEEK1.md), [`STRESS_TESTS.md`](STRESS_TESTS.md),
[`sidecar/DASHBOARD.md`](sidecar/DASHBOARD.md) / [`ALERTS.md`](ALERTS.md).

---

## 1. Actual dev spend

_No billing-console API access; estimated from observed usage. LLM dominates even
in dev; the bulk of the test suite runs on injected fakes at **$0** — only real
turns and real VLM extractions cost money._

| Item | Estimate | Basis |
|---|---|---|
| Anthropic API | **~$60–160** | A few hundred real turns + VLM extractions over dev: load/stress batches, live eval sweeps (50-case golden set × iterations), demos, ad-hoc testing. Mostly Haiku (~$0.02/turn) with earlier Opus work (~$0.15/turn) |
| Railway hosting | **~$50–100** | **4 services** now (OpenEMR app, sidecar, MySQL, **Qdrant**) at ~$20–40/mo over ~1–2 months |
| Cohere (RAG embed + rerank) | **~$0–5** | Free/near-free tier during dev |
| Braintrust (observability) | **$0** | Free tier |
| **Total dev** | **~$110–265** | LLM is the dominant line even in development |

*Week-2 delta vs. MVP:* adding the Qdrant service nudged infra up ~$10–20/mo; LLM
spend is unchanged in shape (Haiku default).

---

## 2. Measured unit economics — live Haiku (real turns)

Three real turn types against the heavy demo chart (pid 1), from the live
observability trace. **Input tokens dominate**: cost is the *chart context we
send* (15K–80K in), not the answer (hundreds–low-thousands out).

| Turn type | Model calls | Tool calls | Input tok | Output tok | **Haiku cost** | _(same turn on Opus)_ |
|---|---|---|---|---|---|---|
| Chart summary | 2 | 1 | 14,565 | ~200 | **$0.0156** | _$0.100_ |
| Focused Q&A + guideline (RAG) | 2 | 2 | 17,817 | 589 | **$0.0208** | _$0.102_ |
| Full sign-out handoff | 3 | 8 | 81,124 | 2,791 | **$0.0951** | _$0.491_ |

- **Blended working figure: ~$0.02 / turn** (Haiku, no caching). ~7× cheaper than
  the naive Opus $0.15/turn.
- **VLM extraction** (`/extract`, per document upload): one vision call + ≤2,048
  output tokens ≈ **$0.01–0.02** on Haiku — a one-off per-upload cost, *not*
  per-turn (but see §6 re `get_intake_form`).
- **RAG retrieval** adds a Cohere embed/rerank (fractions of a cent) + one extra
  model call — already included in the focused-RAG row.

---

## 3. Latency — p50 / p95 (measured)

### Single-user (concurrency 1, live Haiku)

| Scenario | **p50** | **p95** | min / mean / max | Errors |
|---|---|---|---|---|
| Chart summary (`/ask`) | **4.4 s** | **6.5 s** | 3.5 / 4.6 / 6.5 s | 0 |
| Focused Q&A + guideline (RAG) | **5.5 s** | **7.5 s** | 5.0 / 5.8 / 7.5 s | 0 |
| _Opus baseline (Week 1, ref)_ | _5.4 s_ | _12.5 s_ | _5.1 / 7.4 / — s_ | _0_ |

### Under concurrent load

| Concurrent users | p50 | p95 | p99 | Throughput | Errors |
|---|---|---|---|---|---|
| **10 in-flight** (Haiku) | **4.1 s** | **5.1 s** | 5.3 s | 2.2 req/s | **0 %** |
| _10 (Opus-era)_ | _5.8 s_ | _8.1 s_ | _11.5 s_ | _1.3 req/s_ | _0 %_ |
| _50 (Opus-era)_ | _8.9 s_ | _13.0 s_ | _15.5 s_ | _3.2 req/s_ | _0 %_ |

Haiku holds **p95 ~5 s even at 10 concurrent** with zero errors — well under the
`ALERTS.md` p95 < 10 s SLO.

### Sidecar overhead is negligible (proves where the time goes)

| Probe | p50 | p95 | Throughput |
|---|---|---|---|
| `GET /health` (no dependencies) | **1.1 ms** | **4.0 ms** | ~5,470 req/s |
| `GET /ready` (dependency reachability checks) | 937 ms | 1,190 ms | network-bound |

The process itself answers in ~1 ms at ~5.5k req/s; all real latency is in the
dependencies (the model call and network round-trips).

### SLO posture (vs. `W2_ARCHITECTURE.md` §7 targets)

| SLO | Target p95 | Measured p95 | Status |
|---|---|---|---|
| Agent turn (`/ask`) | < 15 s | 6.5 s (7.5 s w/ RAG) | ✅ comfortable headroom |
| Readiness (`/ready`) | < 1.5 s | 1.19 s | ✅ |
| Liveness (`/health`) | < 10 ms | 4.0 ms | ✅ |

---

## 4. Bottleneck analysis

**Latency bottleneck: the Claude model call (~90–95 % of a turn).**
- `/health` p50 = 1.1 ms proves the sidecar is thin; the OpenEMR boundary and
  Railway MySQL are ~0.4 s each; everything else is the LLM.
- The only real lever is **model tier** — already pulled (Haiku ~2× faster than
  Opus). Sonnet measured *slower* than Opus on real turns (verbose output), so it
  is not a latency win.
- Secondary lever: **input volume** — the 81K-token handoff is slower and costlier
  than a 15K-token summary; trimming context helps both axes.
- **RAG adds ~1 s** (embed + rerank + one extra model call); the dense path has a
  2 s timeout + circuit breaker so a slow Qdrant fails fast rather than stalling.

**Cost bottleneck: input tokens (chart context), not output.**
- Every turn sends 15K–80K input tokens vs. hundreds–low-thousands out. Levers are
  all *send less / reuse more*: **prompt caching** (system prompt + tool schemas +
  patient summary are identical across a clinician's several questions on one
  patient) and **context trimming**. Output-side optimization is a rounding error.
- Minimum-necessary design is a **cost** strategy as much as a compliance one.

**Under concurrency:** the bottleneck shifts to **provider queueing / rate
limits**, never the sidecar (peak ~46 MB RSS, < 15 % of one core per turn).
Capacity planning is about Anthropic throughput, not sidecar CPU.

---

## 5. Projected production cost

Usage model (from `USER.md`): an ED attending runs the agent at ~3 points per
patient × ~50 turns/shift × ~20 shifts/mo ≈ **~1,000 turns / active clinician /
month**. "Users" = *active clinicians*; cost scales with **turns**, not accounts.
`LLM $/mo = users × 1,000 turns × $/turn`.

- **Haiku, no caching** = measured **$0.02/turn**.
- **Optimized** = prompt caching (static ~14.5K reads at ~0.1×) + context trimming
  ≈ **~$0.01/turn** (~50 % cut; more on multi-question sessions).

| Active users | Turns / mo | **LLM/mo (Haiku)** | **LLM/mo (optimized)** | Infra/mo | Dominant lever |
|---|---|---|---|---|---|
| **100** | 100K | **~$2K** | **~$1K** | ~$100 | turn on prompt caching |
| **1K** | 1M | **~$20K** | **~$10K** | ~$1–2K | caching + rate-limit tier |
| **10K** | 10M | **~$200K** | **~$100K** | ~$10–20K | committed LLM capacity |
| **100K** | 100M | **~$2M** | **~$1M** | ~$100–300K | negotiated $/token; self-host cheap tier |

_The original all-Opus naive projection was $15K → $15M across the same tiers.
Choosing Haiku already bought a ~7× reduction — before any caching._ LLM cost
dwarfs infrastructure at every level, so **the scaling strategy is driving
`$/turn` down**, not adding servers. Architectural changes required at each tier
(prompt caching → read replicas + rate-limit tier → committed throughput +
context compression → negotiated contract / self-hosted cheap tier) are detailed
in [`COST_ANALYSIS_W2_MVP.md`](COST_ANALYSIS_W2_MVP.md) §6.

---

## 6. Why this is NOT `cost-per-token × n`

1. **`$/turn` is not constant** — it falls with architecture (Opus→Haiku:
   $0.15→$0.02; caching + trimming: →$0.01). Naive linear scaling overstates the
   bill several-fold.
2. **Input, not output, is the cost** — chart context dominates; every lever is
   *send less / reuse more*. Minimum-necessary is a cost lever.
3. **Infra is sublinear** (shared, autoscaled, cached), but **new cost categories
   appear** at each tier (BAA/enterprise commit, a compliance data platform,
   multi-region, an SRE org) that don't exist at 100 users.
4. **Non-linear cliffs** change the architecture, not just the bill: Anthropic
   **rate limits** force capacity deals (1K→10K); **real PHI** forces BAA/ZDR (any
   real deploy); sustained volume flips **build-vs-buy** toward self-hosting the
   cheap tier (~100K).
5. **Usage intensity varies by user** — the ED is a worst case; model the *turns*,
   not the accounts.

---

## 7. Open findings / action items (status)

1. **Dashboard `cost_usd` is still mispriced for Haiku (overstates ~5×).**
   `sidecar/observability.py` `_PRICING` has only a `claude-opus-4-8` entry, and
   `server.py` constructs `TraceCollector()` **without** the configured model — so
   every live Haiku turn logs Opus-priced cost (a $0.0156 turn logs as ~$0.078).
   **Status: OPEN.** Fix: add Haiku 4.5 (`$1/$5`) to `_PRICING` and pass the model
   into `TraceCollector(model=...)`. Low-risk, high-value. *(The measured `$/turn`
   figures in this report are computed from raw token counts at Haiku rates, so
   they are correct despite the dashboard bug.)*
2. **`get_intake_form` re-runs the VLM extractor per intake question.** Fine at MVP
   volume; at scale it adds a per-turn vision cost + latency spike. Cache the
   `/extract` result server-side (keyed by pid/document) and read the cache first.
   **Status: staged** (documented as the "Option 2" follow-up).
3. **Context trimming is the next cost/latency win.** The 81K-token handoff is 5×
   the cost and materially slower than a focused turn; summarize/trim chart context
   before sending on the heavy synthesis path. **Status: open lever.**
4. **Per-tool Braintrust spans now emit** (`type=tool`), so tool executions / error
   rate / duration populate going forward — the observability surface for the cost
   drivers above is now complete. **Status: shipped.**

_Latency captured 2026-07-15 via `sidecar/perf/loadtest.py` against the live
Railway Haiku sidecar; per-turn tokens from the live observability trace, priced
at Haiku 4.5 rates. Re-derive `$/turn` from Braintrust `metrics.cost_usd` once
finding #1 lands._
