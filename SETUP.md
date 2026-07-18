# SETUP — Run the repo locally

A complete, from-scratch guide to clone **OpenEMR Agent Forge** from GitLab and
get every layer running on your machine: the OpenEMR PHP app, the Python AI
sidecar, the guideline vector store, and the eval/CI gate. Everything here runs
on **synthetic data only** — never point it at real PHI.

> Companion docs: architecture in [`ARCHITECTURE.md`](ARCHITECTURE.md) /
> [`W2_ARCHITECTURE.md`](W2_ARCHITECTURE.md), diagram in
> [`W2_ARCHITECTURE_DIAGRAM.md`](W2_ARCHITECTURE_DIAGRAM.md), CI gate in
> [`W2_CI_EVIDENCE.md`](W2_CI_EVIDENCE.md). This file is the *how to run it*
> reference; those explain *how it works*.

---

## 0. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Docker Desktop | current | runs the OpenEMR + MySQL + Selenium dev stack |
| Python | 3.12 (3.9+ works with user-site deps) | the AI sidecar |
| Git | current | clone + the pre-push eval hook |
| An SSH key registered on `labs.gauntletai.com` | — | to clone over SSH |

Optional (only if you want the *live* AI path, not just the offline test suite):
an `ANTHROPIC_API_KEY`, and — for reranked RAG and dashboards — `COHERE_API_KEY`
and `BRAINTRUST_API_KEY`.

---

## 1. Clone from GitLab

The canonical remote is GitLab over SSH (port **22022**):

```bash
git clone ssh://git@labs.gauntletai.com:22022/kevinreynolds/agent-forge.git
cd agent-forge
```

If your SSH key lives under a non-default name, add a host block to `~/.ssh/config`:

```
Host labs.gauntletai.com
    HostName labs.gauntletai.com
    Port 22022
    User git
    IdentityFile ~/.ssh/id_ed25519
```

Verify: `git remote -v` should show
`ssh://git@labs.gauntletai.com:22022/kevinreynolds/agent-forge.git`.

---

## 2. Start the OpenEMR stack (PHP app + MySQL)

The repo ships a ready-made dev stack:

```bash
cd docker/development-easy
docker compose up --detach --wait
```

First run pulls images and builds the database — several minutes. `--wait` blocks
until the containers report healthy.

- **App:** http://localhost:8300/ or https://localhost:9300/
- **Login:** `admin` / `pass`
- **phpMyAdmin:** http://localhost:8310/

The AI Co-Pilot module (`interface/modules/custom_modules/oe-module-ai-agent`) is
bind-mounted into the container, so PHP edits are live with no rebuild.

### Module config

The module reads `interface/modules/custom_modules/oe-module-ai-agent/config.local.php`
(gitignored). It holds the HS256 **`signing_key`** the sidecar and the boundary
share, and `dev_token_mint` (a synthetic-demo-only token mint that bypasses the
browser session — **never enable against real PHI**). If the file is absent, copy
the shipped example and set a 64-char random `signing_key`.

---

## 3. Seed synthetic demo data

The dev database starts **empty** (reference/config data only, no patients). Seed
fictional patients — **no real PHI, ever**. Two options:

**A. Bulk demographics** (100 synthetic patients) — see the
[README "Seeding demo data"](README.md#seeding-demo-data) section for the
`demo-data-generator` staging-table recipe.

**B. Eval fixtures** (the two data-dependent eval patients: a stale-active
Warfarin chart and a wrong-chart identity mismatch):

```bash
python sidecar/evals/seed_eval_patient.py | \
  docker exec -i development-easy-mysql-1 mariadb -uroot -proot openemr
```

The script prints **idempotent** SQL, so re-running is safe.

---

## 4. Run the AI sidecar

The sidecar is a dependency-light Python service (`sidecar/server.py`, stdlib
HTTP server). It runs **out-of-process** from PHP so a multi-second model call
never blocks a PHP-FPM worker.

```bash
cd sidecar
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # anthropic, pydantic, langgraph, cohere, qdrant-client, braintrust
```

Create `sidecar/.env` (gitignored):

```bash
ANTHROPIC_API_KEY=sk-ant-...             # required for the live /ask + /extract path
BRAINTRUST_API_KEY=                      # optional — observability dashboard
COHERE_API_KEY=                          # optional — dense embeddings + rerank (RAG degrades to stubs without it)
QDRANT_URL=http://localhost:6333         # optional — dense vector store (see §5)
OE_AI_AGENT_SIGNING_KEY=<same 64-char key as config.local.php's signing_key>
OE_AI_AGENT_SUMMARY_URL=http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php
OE_AI_AGENT_MODEL=claude-haiku-4-5-20251001   # production tier; omit for the Opus default
```

Start it:

```bash
python server.py          # binds 127.0.0.1:8900 by default (OE_AI_AGENT_PORT to override)
```

Verify the three probes:

```bash
curl -s localhost:8900/health   # {"status":"ok","service":"ai-sidecar"}
curl -s localhost:8900/ready    # {"ready":..., "checks":{openemr, llm, observability[, qdrant]}}
curl -s localhost:8900/metrics  # live ops snapshot (ingestion, extraction, retrieval, routing, alerts)
```

`/ready` reports each dependency by name and returns **503** only on a
connection-level failure — a `401` from OpenEMR's `summary.php` counts as
*reachable* (the boundary is up, it just wants a token).

> The card's browser JS points at the sidecar origin; for a purely local app +
> local sidecar, ensure the module config's sidecar URL and `OE_AI_AGENT_ALLOW_ORIGIN`
> line up with `http://localhost:8300`.

---

## 5. (Optional) Local Qdrant for dense RAG

Hybrid retrieval works fully offline with deterministic stub embeddings, so this
is optional. For the real dense path, run Qdrant and point `QDRANT_URL` at it:

```bash
docker run -p 6333:6333 qdrant/qdrant:v1.16.1
```

With `QDRANT_URL` set, `/ready` gains a `qdrant` probe and the guideline index is
built into Qdrant on first use. Without it, retrieval uses the in-process index —
no code change, same `VectorIndex` protocol.

---

## 6. Verify everything with the test suites

**Offline sidecar suite** (no LLM, no network, no secrets — the CI-blocking gate):

```bash
python -m pytest -c sidecar/pytest.ini sidecar/tests
```

**Install the pre-push eval gate** (blocks a push that regresses the golden set):

```bash
bash sidecar/hooks/install.sh
```

**PHP module isolated tests** (in the container):

```bash
docker exec development-easy-openemr-1 bash -lc \
  'cd /var/www/localhost/htdocs/openemr && AI_DB_HOST=mysql ./vendor/bin/phpunit -c phpunit.xml --testsuite unit'
```

**Widget JS tests** (host, jsdom):

```bash
node_modules/.bin/jest interface/modules/custom_modules/oe-module-ai-agent
```

---

## 7. (Optional) Live agent smoke test

With `ANTHROPIC_API_KEY` set and a seeded patient, drive a real turn:

```bash
cd sidecar && python -m eval --live --threshold 0.9
```

This exercises the production agent + LLM over the boundary (mints a pid-scoped
JWT from `OE_AI_AGENT_SIGNING_KEY`). It is the same sweep the non-blocking
`eval:live` CI job runs.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `git clone` hangs / permission denied | SSH key/port | add the `~/.ssh/config` host block in §1; key must be registered on GitLab |
| App up but Co-Pilot card errors on ask | sidecar down or CORS | check `/health`; align sidecar URL + `OE_AI_AGENT_ALLOW_ORIGIN` with the app origin |
| `/ready` shows `llm: unreachable` | no/invalid `ANTHROPIC_API_KEY` | set it in `sidecar/.env` (offline tests still pass without it) |
| `/ready` shows `qdrant: not_configured` | `QDRANT_URL` unset | expected — RAG uses the in-process index; set it only for the dense path (§5) |
| Extraction 401 at the boundary | `signing_key` mismatch | `OE_AI_AGENT_SIGNING_KEY` must equal `config.local.php`'s `signing_key` |
| `pre-push` hook: "cannot run the eval gate" | host Python lacks deps | `pip install -r sidecar/requirements-dev.txt`, or run the `w2-sidecar-test` container, or `git push --no-verify` if the push genuinely doesn't need it |
