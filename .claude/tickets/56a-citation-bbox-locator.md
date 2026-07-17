---
id: 056a
title: Citation bounding-box locator + extract-response overlay contract
status: done
depends_on: []
branch: ticket/56a-citation-bbox-locator
base_branch: main
test_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests/test_bbox_locator.py -q"
full_suite_command: "docker exec w2-sidecar-test python -m pytest -c pytest.ini tests -q"
attempts: 1
---

## Description
First half of T56 (option 1 — deterministic locator on known page geometry). Add a pure, deterministic word-box locator (`sidecar/bbox.py`) that, given a page's OCR word geometry (`{text, x, y, w, h}` per word) and a fact's `source_citation` quote, returns the bounding box(es) that cover that quote on the page — the union of the matched contiguous word run, split into one box per line. The word-geometry source is an INJECTABLE seam (no OCR system dependency): `default_extract_builder` gains an optional `word_geometry` provider; when supplied, the `/extract` response carries `citation_boxes` + the page dimensions so the card (T56b) can draw the overlay scaled to the displayed image. When no provider is supplied the response is unchanged (backward compatible). Guards architecture §9: "an overlay box drawn on the wrong value, or a crash when the quote is absent."

## Acceptance criteria
- [ ] `sidecar/bbox.py` exposes `locate_citation_boxes(words, quote)` returning a list of `{x, y, w, h}` boxes (geometry space).
- [ ] A single-word quote returns exactly that word's box; a multi-word contiguous quote returns one union box spanning those words.
- [ ] Matching is normalization-tolerant (case + surrounding punctuation ignored), so `"HbA1c: 7.4%"` matches the words `HbA1c` `7.4` `%`.
- [ ] A quote absent from the page returns `[]` (no crash) — as does an empty quote or empty word list.
- [ ] A matched run spanning two lines (a vertical gap) returns one box per line, not a single tall box across both.
- [ ] `default_extract_builder(..., word_geometry=None)`: with a provider returning `{words, page_width, page_height}`, the extract body gains `citation_boxes` (located for the fact's `source_citation`) plus `page_width`/`page_height`; with no provider the body is unchanged (no `citation_boxes` key).

## Test plan (orchestrator authors these)
- `sidecar/tests/test_bbox_locator.py` — locator unit tests (single/multi word, normalization, absent, multi-line) + the `/extract` response-overlay wiring via an injected geometry provider (and backward-compat with none).
