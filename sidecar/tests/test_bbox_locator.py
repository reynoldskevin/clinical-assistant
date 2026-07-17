"""T56a acceptance tests (LOCKED) — citation bounding-box locator + overlay contract.

Option 1 of T56 (deterministic locator on known page geometry — no OCR system
dependency). `locate_citation_boxes(words, quote)` maps a fact's `source_citation`
quote onto the page's word geometry and returns the covering box(es); the word
geometry arrives via an INJECTABLE provider so the `/extract` response can carry
`citation_boxes` for the card (T56b) to draw. Guards architecture §9 — "an overlay
box drawn on the wrong value, or a crash when the quote is absent."

Deterministic: fixed word-geometry lists + a monkeypatched extractor; no OCR, no
live API, no sockets.
"""
import json

import server
from bbox import locate_citation_boxes


def W(text, x, y, w, h):
    return {"text": text, "x": x, "y": y, "w": w, "h": h}


# A one-line page: "HbA1c 7.4 % elevated" laid out left to right at y=100.
LINE = [
    W("HbA1c", 10, 100, 60, 20),
    W("7.4", 80, 100, 30, 20),
    W("%", 115, 100, 10, 20),
    W("elevated", 135, 100, 90, 20),
]


# --- 1. locator basics -------------------------------------------------------

def test_single_word_quote_returns_that_words_box():
    boxes = locate_citation_boxes(LINE, "elevated")
    assert boxes == [{"x": 135, "y": 100, "w": 90, "h": 20}]


def test_multi_word_contiguous_quote_returns_one_union_box():
    boxes = locate_citation_boxes(LINE, "HbA1c 7.4")
    # Union spans from HbA1c's left (10) to 7.4's right (80+30=110).
    assert boxes == [{"x": 10, "y": 100, "w": 100, "h": 20}]


def test_matching_is_normalization_tolerant():
    # Different case, extra whitespace, and surrounding punctuation still match
    # the words HbA1c / 7.4 (punctuation-only tokens like "%" don't participate).
    boxes = locate_citation_boxes(LINE, "  HbA1C,  7.4.  ")
    assert boxes == [{"x": 10, "y": 100, "w": 100, "h": 20}]  # HbA1c(10) .. 7.4(80+30=110) -> w=100


# --- 2. the quote is not on the page ----------------------------------------

def test_absent_quote_returns_empty_without_crashing():
    assert locate_citation_boxes(LINE, "myocardial infarction") == []


def test_empty_quote_or_empty_words_returns_empty():
    assert locate_citation_boxes(LINE, "") == []
    assert locate_citation_boxes([], "anything") == []


# --- 3. a match spanning two lines yields one box per line -------------------

def test_multiline_match_returns_one_box_per_line():
    words = [
        W("chronic", 10, 100, 70, 20),
        W("kidney", 85, 100, 60, 20),
        # next line (big vertical gap)
        W("disease", 10, 140, 70, 20),
        W("stage", 85, 140, 50, 20),
    ]
    boxes = locate_citation_boxes(words, "chronic kidney disease stage")
    assert boxes == [
        {"x": 10, "y": 100, "w": 135, "h": 20},   # line 1: chronic..kidney
        {"x": 10, "y": 140, "w": 125, "h": 20},   # line 2: disease..stage
    ]


# --- 4. /extract response overlay wiring ------------------------------------

class _Fact:
    def __init__(self, source_citation):
        self.source_citation = source_citation
        self.demographics = None

    def model_dump(self):
        return {"source_citation": self.source_citation}


def _fake_result(source_citation):
    return type(
        "R",
        (),
        {
            "doc_type": "lab_pdf",
            "confidence": 0.92,
            "low_confidence": False,
            "unsupported_fields": [],
            "fact": _Fact(source_citation),
        },
    )()


def test_extract_response_carries_citation_boxes_when_geometry_is_provided(monkeypatch):
    monkeypatch.setattr(server, "build_chart_boundary", lambda *a, **k: object())
    monkeypatch.setattr(server, "attach_and_extract", lambda *a, **k: _fake_result("HbA1c 7.4"))

    def geometry(pid, document_id, doc_type):
        return {"words": LINE, "page_width": 400, "page_height": 600}

    extract = server.default_extract_builder("http://oe/summary.php", None, word_geometry=geometry)
    body = extract(1, "jwt", 5, "lab_pdf")

    # citation_boxes is a per-field map {field: [boxes]} (T56d). The only string
    # field on this fake fact is source_citation, which locates "HbA1c 7.4".
    assert body["citation_boxes"] == {"source_citation": [{"x": 10, "y": 100, "w": 100, "h": 20}]}
    assert body["page_width"] == 400
    assert body["page_height"] == 600
    # sanity: it's JSON-serializable (crosses the wire to the card)
    json.dumps(body)


def test_extract_response_unchanged_when_no_geometry_provider(monkeypatch):
    monkeypatch.setattr(server, "build_chart_boundary", lambda *a, **k: object())
    monkeypatch.setattr(server, "attach_and_extract", lambda *a, **k: _fake_result("HbA1c 7.4"))

    extract = server.default_extract_builder("http://oe/summary.php", None)  # no word_geometry
    body = extract(1, "jwt", 5, "lab_pdf")

    assert "citation_boxes" not in body
    assert body["ok"] is True
