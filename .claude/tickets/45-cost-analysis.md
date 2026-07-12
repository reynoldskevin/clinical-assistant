---
id: 45
title: AI cost analysis — dev spend + 100/1K/10K/100K projections + architecture
status: ready-for-merge
depends_on: [38]
branch: ticket/45-cost-analysis
base_branch: main
test_command: "python -m pytest sidecar/tests/test_cost_analysis_doc.py"
full_suite_command: "python -m pytest -c sidecar/pytest.ini sidecar/tests"
attempts: 1
---

## Description
Deliverable: actual dev spend + projected production costs at 100/1K/10K/100K
users, with the architectural changes needed at each level — explicitly not
cost-per-token x n. COST_ANALYSIS.md grounds the analysis in MEASURED per-turn
token/cost (three real turns from the sidecar observability trace: $0.10 focused
to $0.49 complex, input-token-dominated), estimates dev spend (~$100-250,
LLM-dominated), models ED usage (~1,000 turns/user/mo), and projects naive vs
optimized (prompt caching + model tiering + context trimming) LLM cost + infra +
new cost categories at each scale, with the per-level architecture and five
reasons the cost is non-linear.

## Acceptance criteria
- [x] Dev spend (estimated, honest about no billing access) + measured unit
      economics ($/turn, input vs output).
- [x] 100/1K/10K/100K projection (naive vs optimized) + infra.
- [x] Architectural changes at each level; the not-cost-per-token-x-n argument.
- [x] Guard test pins the doc; full suite green.
