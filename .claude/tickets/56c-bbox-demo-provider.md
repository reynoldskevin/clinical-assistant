---
id: 056c
title: Local demo geometry provider — make the bbox overlay viewable on localhost
status: done
depends_on: [056a, 056b]
branch: ticket/56c-bbox-demo-provider
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_bbox_demo_provider.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Follow-up to T56a/T56b: wire a flag-gated demo word-geometry provider so the citation overlay is viewable in the live card on localhost. Adds a committed word-geometry fixture for the synthetic intake form (`synthetic_intake_geometry.json`, generated to match the committed Arial PNG) and a provider `intake_demo_geometry(pid, document_id, doc_type)` that returns it for `intake_form` uploads only when `OE_AI_AGENT_BBOX_DEMO` is enabled (off by default → production unchanged). Broadens the (word-geometry-only) box computation in `default_extract_builder` to locate every non-empty grounded fact VALUE on the page — so the overlay reliably highlights each extracted value, not just a single citation quote. The live `main()` passes this provider so, with the flag set, uploading the synthetic intake form shows the overlay.

## Acceptance criteria
- [ ] `sidecar/demo_bbox.py` exposes `intake_demo_geometry(pid, document_id, doc_type)`: returns `{words, page_width, page_height}` for `doc_type == "intake_form"` when `OE_AI_AGENT_BBOX_DEMO` is truthy; returns `None` for other doc types and when the flag is unset (off by default).
- [ ] The committed fixture `sidecar/fixtures/documents/synthetic_intake_geometry.json` has `page_width`/`page_height` and a non-empty `words` list; the real `locate_citation_boxes` finds a non-empty box for each synthetic intake field value against it.
- [ ] When a `word_geometry` provider yields geometry, `default_extract_builder` sets `citation_boxes` to the union of boxes located for every non-empty STRING value in the extracted fact (comprehensive provenance), plus `page_width`/`page_height`; with no provider the body is unchanged (no `citation_boxes`).
- [ ] Production default unchanged: with `OE_AI_AGENT_BBOX_DEMO` unset the provider yields `None`, so the `/extract` body carries no `citation_boxes`.

## Test plan (orchestrator authors these)
- `sidecar/tests/test_bbox_demo_provider.py` — provider flag/doc-type gating, the geometry fixture locates each field value, and the broadened multi-value box computation in `default_extract_builder`.
