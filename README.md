[![Syntax Status](https://github.com/openemr/openemr/actions/workflows/syntax.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/syntax.yml)
[![Styling Status](https://github.com/openemr/openemr/actions/workflows/styling.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/styling.yml)
[![Testing Status](https://github.com/openemr/openemr/actions/workflows/test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/test.yml)
[![JS Unit Testing Status](https://github.com/openemr/openemr/actions/workflows/js-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/js-test.yml)
[![PHPStan](https://github.com/openemr/openemr/actions/workflows/phpstan.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/phpstan.yml)
[![Rector](https://github.com/openemr/openemr/actions/workflows/rector.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/rector.yml)
[![ShellCheck](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml)
[![Docker Compose Linting](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml)
[![Dockerfile Linting](https://github.com/openemr/openemr/actions/workflows/docker-lint-hadolint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/docker-lint-hadolint.yml)
[![Isolated Tests](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml)
[![Inferno Certification Test](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml)
[![Composer Checks](https://github.com/openemr/openemr/actions/workflows/composer.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer.yml)
[![Composer Require Checker](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml)
[![API Docs Freshness Checks](https://github.com/openemr/openemr/actions/workflows/api-docs.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/api-docs.yml)
[![codecov](https://codecov.io/gh/openemr/openemr/graph/badge.svg?token=7Eu3U1Ozdq)](https://codecov.io/gh/openemr/openemr)

[![Backers on Open Collective](https://opencollective.com/openemr/backers/badge.svg)](#backers) [![Sponsors on Open Collective](https://opencollective.com/openemr/sponsors/badge.svg)](#sponsors)

# OpenEMR Agent Forge

## Contents
[Installation](#installation)\
[Seeding demo data](#seeding-demo-data)\
[Architecture Diagram](#architecture-diagram)\
[Engineering Deliverables](#engineering-deliverables)\
[Submission Requirements](#submission-requirements) 

## Installation

### 1. Install Docker

Easiest is Docker Desktop for Mac:

<!-- with Homebrew: -->
brew install --cask docker
<!-- then launch it once so the engine starts: -->
open -a Docker

Or download from https://www.docker.com/products/docker-desktop/

Wait until the Docker whale icon in the menu bar says it's running.

### 2. Start the OpenEMR stack

The repo ships a ready-made dev stack:

cd /Users/kevin/Sites/openemr-base-clean/docker/development-easy
docker compose up --detach --wait

First run pulls images and builds the database — it takes several minutes. --wait blocks until containers are healthy.

### 3. Open it

- App: http://localhost:8300/ or https://localhost:9300/
- Login: admin / pass
- phpMyAdmin: http://localhost:8310/


## Seeding demo data

The dev database starts **empty** — a fresh OpenEMR install ships only reference/
config data (code sets, list_options), no patients. We seed synthetic patients
for testing; **no real PHI is ever used.**

### Approach used: OpenEMR `demo-data-generator` (100 patients, demographics-only)

Generates fictional patients via OpenEMR's official tool and loads them into the
dev DB.

```bash
# 1. Clone + install the generator (Python)
git clone --depth 1 https://github.com/openemr/demo-data-generator.git
cd demo-data-generator
python3 -m venv venv && venv/bin/pip install .

# 2. Generate N patients as SQL
venv/bin/demodata patients --count 100 > gen_patients.sql

Two gotchas (the generator is from 2017; the schema is 8.x):
1. It emits a column interpretter that no longer exists → every INSERT aborts.
2. It writes '' for numeric columns, which STRICT_TRANS_TABLES rejects.

We work around both by loading into a text staging table, then copying only
the still-valid columns into patient_data:

MYSQL="docker exec -i development-easy-mysql-1 mariadb -uroot -proot openemr"

# 3. Build a staging table with ALL generator columns as TEXT
GENCOLS="$(sed -n '1p' gen_patients.sql | sed -E 's/.*\(([^)]*)\) VALUES.*/\1/' | tr -d ' ')"
STAGE_DDL=$(echo "$GENCOLS" | tr ',' '\n' | sed 's/.*/`&` TEXT/' | paste -sd ',' -)
VALIDCOLS=$(echo "$GENCOLS" | tr ',' '\n' | grep -vx 'interpretter' | sed 's/.*/`&`/' | paste -sd ',' -)
echo "DROP TABLE IF EXISTS gen_stage; CREATE TABLE gen_stage ($STAGE_DDL);" | $MYSQL

# 4. Load generated rows into staging (retarget table, relax strict mode)
( echo "SET SESSION sql_mode='';"; sed 's/`patient_data`/`gen_stage`/' gen_patients.sql ) | $MYSQL

# 5. Copy the valid columns into patient_data, then drop staging
echo "SET SESSION sql_mode='';
    INSERT IGNORE INTO patient_data ($VALIDCOLS) SELECT $VALIDCOLS FROM gen_stage;
    DROP TABLE gen_stage;" | $MYSQL

Result: 100 patients in patient_data. Demographics only — no encounters,
problems, meds, or results (the generator doesn\'t produce clinical data).
```

## Architecture Diagram

A read-only AI Clinical Co-Pilot attached to OpenEMR through a custom module. The
LLM tool-use loop runs **out-of-process** in a Python sidecar (so the multi-second
call never blocks a PHP-FPM worker); the agent reads the chart only through an
**audited, patient-scoped HTTP boundary**, never a direct DB connection.

### Component & integration view

```mermaid
flowchart TB
    subgraph BROWSER["Clinician's Browser — patient dashboard"]
        CARD["AI Clinical Co-Pilot card · agent-widget.js<br/>(injected via demographics render-top event)"]
    end

    subgraph OE["OpenEMR — PHP, same origin (oe-module-ai-agent)"]
        TOKEN["token.php — credential mint<br/>① session auth + CSRF<br/>② ACL gate: patients/med<br/>③ mint pid-scoped JWT · HS256 · ~5 min"]
        BND["summary.php / read.php — audited read boundary<br/>• verify JWT · cross-pid → 403 (fail closed)<br/>• PatientSummaryService · minimum-necessary<br/>• DatabaseBoundaryAuditLogger → log table"]
        DB[("MySQL · openemr")]
    end

    subgraph SIDECAR["AI Sidecar — Python, out-of-process (:8900 / Railway)"]
        API["server.py — /ask/stream (SSE), /ask"]
        AGENT["ClaudeAgent tool-use loop · agent.py<br/>• ≤ 8 tool calls/turn<br/>• truncation + partial-failure disclosures"]
        GATE["Verification gate · verification.py<br/>V1 strip · V2 demote · V3/V6/V7 block"]
        CONV["Conversation store · conversation.py<br/>ephemeral · pid-scoped · TTL · no PHI at rest"]
        OBS["Observability · observability.py / factory.py<br/>tokens · cost · tools · optional Braintrust"]
    end

    CLAUDE["Anthropic Claude API · claude-opus-4-8<br/>prod: BAA + Zero Data Retention"]

    CARD -->|"① POST token.php · session cookie + CSRF"| TOKEN
    TOKEN -->|"pid-scoped JWT"| CARD
    CARD -->|"② POST /ask/stream · Bearer JWT"| API
    API --> AGENT
    AGENT <-->|"tool calls · Bearer JWT (same token)"| BND
    BND --> DB
    AGENT <-->|"messages + tool results"| CLAUDE
    AGENT -->|"complete draft"| GATE
    GATE -->|"gated answer"| API
    AGENT -.->|"multi-turn"| CONV
    AGENT -.->|"trace"| OBS
    API -->|"SSE · status live · answer buffered+gated last"| CARD
```

### Request-sequence view (one turn, end to end)

```mermaid
sequenceDiagram
    actor Dr as Clinician
    participant Card as AI Card (browser)
    participant Tok as token.php
    participant SC as Sidecar /ask/stream
    participant B as Boundary summary.php
    participant DB as MySQL
    participant LLM as Claude API

    Dr->>Card: ask about the patient
    Card->>Tok: POST · session cookie + CSRF
    Note over Tok: authn + ACL (patients/med) + pid scope
    Tok-->>Card: pid-scoped JWT (~5 min)
    Card->>SC: POST /ask/stream · Bearer JWT
    SC-->>Card: event: status(start)
    loop tool-use loop (<= 8 calls)
        SC->>LLM: messages + tools
        LLM-->>SC: tool_use(get_patient_summary...)
        SC->>B: read · Bearer JWT
        Note over B: verify JWT (cross-pid->403) · min-necessary · AUDIT
        B->>DB: pid-scoped read
        DB-->>B: rows
        B-->>SC: minimum-necessary summary
        SC-->>Card: event: tool(name, ok)
    end
    LLM-->>SC: final draft (cited)
    Note over SC: verification gate V1/V2/V3/V6/V7<br/>+ truncation / partial-failure disclosures
    SC-->>Card: event: answer (gated) -> done
    Card-->>Dr: rendered answer + citations
```

### Integration seam & trust controls

- **Clean seam, no core changes** — the agent attaches via the `oe-module-ai-agent`
  custom module: a dashboard event injects the card, and two PHP endpoints
  (`token.php`, `summary.php`/`read.php`) are the only touchpoints.
- **Three fail-closed gates** — session + CSRF → **ACL** (`patients/med`) →
  **pid-scoped JWT** (one chart, ~5 min); the boundary re-verifies and 403s on any
  mismatch.
- **Every chart read is audited** at the boundary (who · actual patient-id ·
  purpose · grant/deny).
- **Nothing unverified reaches the clinician** — status streams live, but the
  answer is buffered → verification gate → streamed last; V6 scrubs raw
  identifiers; truncation/partial-failure are disclosed, never silent.
- **No direct DB from the agent** and **no PHI at rest in the sidecar** (ephemeral
  TTL conversation state only).

## Engineering Deliverables
Postman Collection and Environment [here](/postman/)\
Braintrust alerts x5 are document with on-call responses [here](ALERTS.md)\
Week 1 Infrastructure Metrics [here](METRICS_WEEK1.md)\
Stress Test results [here](STRESS_TESTS.md)

## Submission Requirements
Eval dataset [here](EVAL_DATASET.md)\
AI Cost Analysis [here](COST_ANALYSIS.md)