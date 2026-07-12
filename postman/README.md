# OpenEMR AI Clinical Co-Pilot — Postman collection

`oe-ai-agent.postman_collection.json` is a Postman v2.1 collection that drives
the AI Clinical Co-Pilot agent endpoints end to end: mint a scoped token, pull
a patient summary, run chart-read tool calls, and ask the AI sidecar a question
(buffered and streaming).

## What it covers

| # | Request | Endpoint |
|---|---------|----------|
| — | Health (liveness) | `GET {{sidecar_base_url}}/health` |
| — | Readiness (dependencies) | `GET {{sidecar_base_url}}/ready` |
| 1 | Mint dev token | `POST {{openemr_base_url}}/dev_mint.php` |
| 2 | Get patient summary | `POST {{openemr_base_url}}/summary.php` |
| 3 | Chart read: list encounters | `POST {{openemr_base_url}}/read.php` |
| 3b | Chart read: medications | `POST {{openemr_base_url}}/read.php` |
| 3c | Chart read: search notes | `POST {{openemr_base_url}}/read.php` |
| 4 | Ask (buffered) | `POST {{sidecar_base_url}}/ask` |
| 5 | Ask (streaming SSE) | `POST {{sidecar_base_url}}/ask/stream` |

## Health and readiness probes

Two unauthenticated `GET` requests on the sidecar (placed at the top of the
collection) check its operational state — no token required:

- **Health (liveness)** — `GET {{sidecar_base_url}}/health`. Reports whether the
  sidecar process is alive. Always returns `200` if the process is up; it says
  nothing about downstream dependencies.
- **Readiness (dependencies)** — `GET {{sidecar_base_url}}/ready`. Probes the
  meaningful dependencies — OpenEMR (the chart-read boundary), the LLM provider
  (Anthropic), and the observability backend (Braintrust) — and returns `200`
  when all reachable, `503` otherwise. The body carries a per-dependency report.
  A `4xx/5xx` from a dependency counts as *reachable* (the server answered — an
  unauthenticated probe to OpenEMR returns `401`, which proves the boundary is
  up); only a connection-level failure marks a dependency down. Observability is
  reported as `not_configured` (and does not fail readiness) when no Braintrust
  key is set.

## Enable the dev mint gate (synthetic demo only)

The mint endpoint used by request 1 (`dev_mint.php`) is **unauthenticated by
design** and therefore **disabled by default** — it returns `404` until you
turn it on. It exists only so this collection can mint a pid-scoped JWT without
an interactive OpenEMR session.

> ⚠️ **SYNTHETIC DEMO ONLY — NEVER enable on real PHI.** `dev_mint.php`
> bypasses OpenEMR's session, CSRF, and ACL controls by design. Enabling it on
> an instance holding real patient data is a serious security hole.

Enable it one of two ways in the module
(`interface/modules/custom_modules/oe-module-ai-agent/`):

- **Env var:** set `OE_AI_AGENT_DEV_MINT=1` in the container/host environment.
- **Config file:** add `'dev_token_mint' => '1',` to the module's
  `config.local.php`.

Truthy values are `1`, `true`, `yes`, `on` (case-insensitive). Anything else —
or unset — keeps it disabled. The same signing key (`OE_AI_AGENT_SIGNING_KEY` /
`signing_key`) must be configured so minted tokens verify at the boundary.

## Import

1. In Postman: **Import** → **File** → select
   `postman/oe-ai-agent.postman_collection.json`.
2. Import an **environment** to target local or the Railway demo:
   - `postman/oe-ai-agent.local.postman_environment.json` — local dev stack
   - `postman/oe-ai-agent.production.postman_environment.json` — Railway demo
   Select it from the environment dropdown (top-right). Without an environment,
   the collection's built-in variables default to local.

## Run order

Run request **1 (Mint dev token)** first. Its test script saves the returned
token into the collection variable `jwt`, and every later request sends it as
`Authorization: Bearer {{jwt}}`. Then run summary → chart reads → ask in order,
or use the collection runner.

## Variables (local vs Railway)

| Variable | Default (local dev stack) | Notes |
|----------|---------------------------|-------|
| `openemr_base_url` | `http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public` | OpenEMR module `public/` dir |
| `sidecar_base_url` | `http://localhost:8900` | The AI sidecar service |
| `pid` | `1` | Synthetic demo patient id |
| `jwt` | *(empty)* | Populated by request 1 |

To target the **Railway demo**, select the
`OE AI Agent — Production (Railway)` environment (or edit the variables). Its
values point at the deployed hosts:

- `openemr_base_url` → `https://truthful-peace-production-62af.up.railway.app/interface/modules/custom_modules/oe-module-ai-agent/public`
- `sidecar_base_url` → `https://ai-sidecar-production-c492.up.railway.app`

The Railway demo holds **synthetic data only**, so the dev-mint gate
(`OE_AI_AGENT_DEV_MINT=1`) is enabled there for the collection to run. Keep it
enabled **only** on a synthetic-demo deployment — never on real PHI.
