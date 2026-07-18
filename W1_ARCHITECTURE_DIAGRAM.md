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