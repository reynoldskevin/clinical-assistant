---
id: 056f
title: Lab-report demo geometry — citation boxes for lab extractions
status: done
depends_on: [056c, 056d]
branch: ticket/56f-lab-geometry
base_branch: ticket/56e-source-modal
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_bbox_lab_geometry.py tests/test_bbox_demo_provider.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
Backend half of extending the citation overlay to lab extractions. Add a legible synthetic lab-report demo document (`synthetic_lab_report_demo.pdf`, a raster PDF so a client PDF renderer can display its page) plus matching per-word geometry (`synthetic_lab_geometry.json`), and generalize the demo geometry provider so `demo_geometry(pid, document_id, doc_type)` serves both `intake_form` and `lab_pdf` (flag-gated, off by default). With the flag set, a `lab_pdf` extraction now returns the per-field `citation_boxes` map (T56d) locating each grounded lab value (test name, result, reference range, collection date, flag) on the page. The card render for PDFs is the follow-up (T56g).

## Acceptance criteria
- [ ] `demo_geometry(pid, document_id, doc_type)` returns committed geometry for BOTH `intake_form` and `lab_pdf` when `OE_AI_AGENT_BBOX_DEMO` is set; `None` for unknown doc types and when the flag is unset (off by default).
- [ ] The committed `sidecar/fixtures/documents/synthetic_lab_geometry.json` has `page_width`/`page_height` and a non-empty `words` list; the real `locate_citation_boxes` finds a box for each lab value (`Hemoglobin A1c`, `7.4`, `4.0-5.6`, `2026-05-01`, `High`).
- [ ] `sidecar/fixtures/documents/synthetic_lab_report_demo.pdf` exists (a valid single-page PDF).
- [ ] With the flag set, a `lab_pdf` extraction through `default_extract_builder` (geometry via `demo_geometry`) yields a per-field `citation_boxes` MAP with a box list for each locatable lab field value.
- [ ] The existing intake demo path is unchanged (`intake_demo_geometry` still intake-only; `test_bbox_demo_provider.py` stays green).

## Test plan (orchestrator authors these)
- `sidecar/tests/test_bbox_lab_geometry.py` — `demo_geometry` gating for both doc types, the lab geometry fixture locating each lab value, and the per-field lab `/extract` response.
