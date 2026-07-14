---
id: 49
title: LangGraph supervisor + intake-extractor/evidence-retriever workers (logged handoffs)
status: tests-authored
depends_on: [47, 48]
branch: ticket/49-supervisor-graph
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_graph.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Week 2 Stage 3, requirement 3 (multi-agent). Introduce LangGraph; port the Week 1 loop into two worker nodes — `intake-extractor` (T46/T47 tools) and `evidence-retriever` (T48 tools) — under a minimal supervisor that routes: extraction needed? retrieval needed? answer ready? Handoffs are explicit and logged (routing decisions inspectable). Preserve correlation-ID propagation into every worker/VLM/retrieval call, the verification gate, and the pid-scoped boundary. `WorkerResult` typed contract with one supervisor↔worker contract test. Happy path: simple rule-based routing, both workers succeed (retries/timeouts → T58; multi-turn → T55).

## Acceptance criteria
- [ ] LangGraph graph with a supervisor + the two worker nodes.
- [ ] A mixed question ("what changed + what evidence supports it") routes through both workers.
- [ ] Handoffs logged + inspectable (routing decision per hop).
- [ ] Correlation ID propagates into every worker invocation, VLM call, retrieval call.
- [ ] Verification gate + pid-scoped boundary preserved through the graph.
- [ ] `WorkerResult` typed contract; supervisor↔worker contract test green.

## Test plan (orchestrator authors these)
- integration `sidecar/tests/test_graph.py`: mixed question hits both workers (stubbed tools); routing log asserts the handoff sequence; correlation id present on each hop; WorkerResult contract round-trip; extraction-only + retrieval-only questions route to one worker.
