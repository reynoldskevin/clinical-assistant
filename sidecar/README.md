# AI Clinical Co-Pilot — sidecar

A small, stateless HTTP service that answers clinician questions about the
**current patient** by running a bounded Claude tool-use loop over OpenEMR's
read boundary. It holds no PHI and no long-lived secrets: every request carries
a short-lived, patient-scoped JWT that the sidecar forwards to OpenEMR for each
chart read.

## Request path

```
browser (patient dashboard card)
  │  1. POST token.php  (session + CSRF)            → short-lived pid-scoped JWT
  │  2. POST /ask {pid, question}  Authorization: Bearer <jwt>
  ▼
sidecar  server.py
  │  ClaudeAgent.run(question, pid)                 → manual tool-use loop
  │    tool get_patient_summary → POST summary.php  Authorization: Bearer <jwt>
  ▼                                                   (OpenEMR verifies pid scope,
OpenEMR summary.php (read boundary)                    audience, expiry; audits)
  ▲  min-necessary patient summary (JSON)
  │
  ▼  {"answer": "..."}  → rendered into the card
```

The pid is **fixed** for the session: `get_patient_summary` takes no patient
argument, and the JWT is bound to one pid, so the model cannot redirect a lookup
to a different chart. A pid mismatch fails closed at the boundary (403).

## Modules

| File | Role |
|------|------|
| `agent.py` | The bounded tool-use loop. SDK-free and pure — deps injected. |
| `factory.py` | Production wiring: real Anthropic message-creator + HTTP boundary caller. The only place the SDK / network live. |
| `server.py` | Runnable HTTP server (`POST /ask`). `process_ask` is pure and unit-tested. |
| `observability.py` | Trace / token / cost accounting. |
| `eval.py`, `evals/` | Eval harness + YAML cases (safety, UC-1). |

## Running it (local dev stack)

1. Configure the module secret (once). In
   `interface/modules/custom_modules/oe-module-ai-agent/`:

   ```bash
   cp config.local.php.dist config.local.php
   # set signing_key (>=32 bytes) and sidecar_url = http://localhost:8900/ask
   php -r "echo bin2hex(random_bytes(32)) . PHP_EOL;"   # generate a key
   ```

   `config.local.php` is gitignored. The **same** `signing_key` is used to mint
   (token.php) and verify (summary.php) the JWT.

2. Install the runtime dep and run the server:

   ```bash
   pip install -r sidecar/requirements.txt
   export ANTHROPIC_API_KEY=sk-ant-...
   # OE_AI_AGENT_SUMMARY_URL defaults to the dev stack's summary.php on :8300
   python sidecar/server.py
   # → AI sidecar listening on http://127.0.0.1:8900/ask
   ```

3. Open a patient dashboard in OpenEMR and use the **AI Clinical Co-Pilot** card.

### Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `ANTHROPIC_API_KEY` | *(required)* | Claude API key. |
| `OE_AI_AGENT_SUMMARY_URL` | `http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php` | OpenEMR read boundary. |
| `OE_AI_AGENT_ALLOW_ORIGIN` | `*` | CORS origin for the browser → sidecar call. |
| `OE_AI_AGENT_HOST` / `OE_AI_AGENT_PORT` | `127.0.0.1` / `8900` | Bind address. |

> Demo-only: point this at the synthetic-data dev stack. Never at real PHI
> without BAA/ZDR-covered infrastructure and a hardened deployment.

## Tests

No live API calls — the SDK client and the HTTP opener are injected fakes.

```bash
etl/.venv/bin/pytest -c sidecar/pytest.ini sidecar/tests
```

## Pre-push eval gate (git hook)

The GitLab `eval:offline` job blocks merges on the deterministic offline eval
suite (the 50-case golden set + boolean rubrics + per-rubric regression gate).
`sidecar/hooks/pre-push` is the local mirror of that gate: it runs the same
suite on `git push` and blocks the push on any failure, so a regression never
leaves the machine.

Install it once per clone:

```bash
sidecar/hooks/install.sh        # copies the hook into .git/hooks (or core.hooksPath)
```

It runs the suite on host Python when the sidecar deps are importable, otherwise
falls back to the `w2-sidecar-test` container. Bypass sparingly, only when the
push genuinely does not touch the gate:

```bash
git push --no-verify            # or:  SKIP_EVAL_GATE=1 git push
```
