---
id: 49b
title: Activation — wire the evidence_retriever guideline-RAG tool into the live Co-Pilot agent
status: tests-authored
depends_on: [48]
branch: ticket/49b-rag-activation
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_rag_activation.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 0
---

## Description
Activation step (mirrors the Week-1 non-ticket activation that made the card render live): make Week-2 hybrid RAG visible in the RUNNING Co-Pilot. Today `server.default_agent_builder` assembles the Week-1 `ClaudeAgent` with only the chart tools, so T48's `evidence_retriever` is never reachable from the browser `/ask` route. This ticket registers the `evidence_retriever` tool (T48) in the live agent's `extra_tools` so a clinician's guideline question (e.g. "What INR range for warfarin in atrial fibrillation?") drives hybrid retrieval over the synthetic guideline corpus and the answer cites the retrieved guideline chunks. The guideline index is built once at process start (deterministic `build_index`) and reused across requests — never rebuilt per `/ask`. The per-request `TraceCollector` is passed to the tool so retrieval hits + rerank scores land on the turn's trace. Cohere rerank stays guarded (stub fallback offline). Scope is the RAG tool ONLY — wiring the full T49 supervisor graph into `process_ask` and exposing T47 `attach_and_extract` as a tool are deferred (they require streaming/multi-turn reconciliation). Happy path.

## Acceptance criteria
- [ ] The live agent assembled by `server.default_agent_builder` includes an `evidence_retriever` tool spec alongside the existing chart tools (encounter/results/medications/search/documents).
- [ ] The guideline index is built exactly once and reused across agent builds (a per-`/ask` rebuild is a failure — assert build happens once across multiple builder calls).
- [ ] A scripted turn where the model calls `evidence_retriever` returns cited guideline rows (`{citation, text, score}`) as the tool result, so the citations are available to the grounding/verification path.
- [ ] The tool records its retrieval hits + rerank scores on the request's `TraceCollector` (the same observer wired into the agent), visible in `summary()["retrieval_hits"]`.
- [ ] pid-scoped boundary and the verification gate are unaffected; the streaming path (`stream_ask`, which shares `default_agent_builder`) gets the tool for free.
- [ ] Offline/no-key: no network or Cohere key required in CI (guarded stub reranker); existing server/agent tests still green.

## Test plan (orchestrator authors these)
- integration `sidecar/tests/test_rag_activation.py`:
  - the tool-assembly used by `default_agent_builder` includes a spec named `evidence_retriever` with a query-required input schema, alongside the chart tools;
  - the guideline index is a shared singleton — building the agent twice does NOT rebuild the index (assert via a build counter / identity);
  - a `ScriptedCreator` run where the model emits a `tool_use` for `evidence_retriever` yields cited guideline rows in the fed-back tool_result, and the run's `TraceCollector.summary()["retrieval_hits"]` is populated with citations + scores;
  - a guideline query surfaces the expected corpus citation (e.g. the warfarin-INR chunk), proving real retrieval not a stub-empty.

## Deferred (explicit follow-ups, NOT this ticket)
- Wire the T49 supervisor graph into `process_ask` / `stream_ask` (replaces the loop; needs SSE + multi-turn + on_event reconciliation) → its own activation ticket.
- Expose T47 `attach_and_extract` as an on-demand extraction tool (needs a `{document_id, doc_type}` input schema + document selection) → its own activation ticket.
