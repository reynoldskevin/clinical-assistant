"""T56c acceptance tests (LOCKED) — local demo geometry provider.

Wires the citation overlay so it is viewable in the live card on localhost:
a flag-gated `intake_demo_geometry` provider returns committed word geometry for
the synthetic intake form, and `default_extract_builder`'s (geometry-only) box
computation is broadened to locate EVERY non-empty grounded fact value on the page
— so the overlay reliably highlights each extracted value. Off by default:
without `OE_AI_AGENT_BBOX_DEMO` the provider yields None and the response is
unchanged.

Deterministic: monkeypatched extractor + env; reads the committed fixture. No OCR,
no live API.
"""
import json
import os

import server
from bbox import locate_citation_boxes
from demo_bbox import intake_demo_geometry

_GEO = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "documents", "synthetic_intake_geometry.json"
)


# --- 1. provider gating ------------------------------------------------------

def test_provider_returns_geometry_for_intake_form_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_BBOX_DEMO", "1")
    geom = intake_demo_geometry(1, 42, "intake_form")
    assert geom is not None
    assert geom["page_width"] and geom["page_height"]
    assert isinstance(geom["words"], list) and geom["words"]


def test_provider_returns_none_for_non_intake_doc_types(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_BBOX_DEMO", "1")
    assert intake_demo_geometry(1, 42, "lab_pdf") is None


def test_provider_is_off_by_default(monkeypatch):
    monkeypatch.delenv("OE_AI_AGENT_BBOX_DEMO", raising=False)
    assert intake_demo_geometry(1, 42, "intake_form") is None


# --- 2. the committed geometry fixture locates every field value -------------

def test_geometry_fixture_locates_each_synthetic_intake_value():
    geom = json.load(open(_GEO))
    words = geom["words"]
    for value in [
        "Intermittent chest tightness and shortness of breath for 2 weeks",
        "Lisinopril 10 mg once daily",
        "Penicillin (rash)",
        "Father: myocardial infarction at age 60",
    ]:
        assert locate_citation_boxes(words, value), f"no box located for {value!r}"


# --- 3. the broadened multi-value box computation ---------------------------

class _Fact:
    """A fact whose two string values both appear in the injected geometry."""

    def __init__(self):
        self.source_citation = "Lisinopril 10 mg"
        self.demographics = None

    def model_dump(self):
        return {"test_name": "Penicillin", "value": "Lisinopril 10 mg", "source_citation": "Lisinopril 10 mg"}


def _fake_result():
    return type(
        "R",
        (),
        {
            "doc_type": "lab_pdf",
            "confidence": 0.9,
            "low_confidence": False,
            "unsupported_fields": [],
            "fact": _Fact(),
        },
    )()


def test_extract_locates_boxes_for_every_string_fact_value(monkeypatch):
    monkeypatch.setattr(server, "build_chart_boundary", lambda *a, **k: object())
    monkeypatch.setattr(server, "attach_and_extract", lambda *a, **k: _fake_result())

    geom = json.load(open(_GEO))

    def geometry(pid, document_id, doc_type):
        return geom

    extract = server.default_extract_builder("http://oe/summary.php", None, word_geometry=geometry)
    body = extract(1, "jwt", 5, "lab_pdf")

    # citation_boxes is a per-field map {field: [boxes]} (T56d) — one entry per
    # fact field whose value locates on the page, so a fact can be clicked to
    # reveal only its own source.
    cb = body["citation_boxes"]
    assert isinstance(cb, dict) and cb
    assert cb["test_name"] == locate_citation_boxes(geom["words"], "Penicillin")
    assert cb["value"] == locate_citation_boxes(geom["words"], "Lisinopril 10 mg")
    assert body["page_width"] == geom["page_width"]
    assert body["page_height"] == geom["page_height"]
