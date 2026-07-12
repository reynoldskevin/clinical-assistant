# OpenEMR AI Clinical Co-Pilot — Postman collection

`oe-ai-agent.postman_collection.json` is a Postman v2.1 collection that drives
the AI Clinical Co-Pilot agent endpoints end to end: mint a scoped token, pull
a patient summary, run chart-read tool calls, and ask the AI sidecar a question
(buffered and streaming).

## What it covers

| # | Request | Endpoint |
|---|---------|----------|
| 1 | Mint dev token | `POST {{openemr_base_url}}/dev_mint.php` |
| 2 | Get patient summary | `POST {{openemr_base_url}}/summary.php` |
| 3 | Chart read: list encounters | `POST {{openemr_base_url}}/read.php` |
| 3b | Chart read: medications | `POST {{openemr_base_url}}/read.php` |
| 3c | Chart read: search notes | `POST {{openemr_base_url}}/read.php` |
| 4 | Ask (buffered) | `POST {{sidecar_base_url}}/ask` |
| 5 | Ask (streaming SSE) | `POST {{sidecar_base_url}}/ask/stream` |

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
2. Open the collection's **Variables** tab and adjust as needed (see below).

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

To point at a **Railway demo** instead of local, edit `openemr_base_url` and
`sidecar_base_url` to the deployed hostnames, e.g.:

- `openemr_base_url` → `https://<your-openemr>.up.railway.app/interface/modules/custom_modules/oe-module-ai-agent/public`
- `sidecar_base_url` → `https://<your-sidecar>.up.railway.app`

Keep `dev_token_mint` / `OE_AI_AGENT_DEV_MINT` enabled only on the synthetic
demo deployment.
