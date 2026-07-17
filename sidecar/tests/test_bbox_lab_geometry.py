"""T56f acceptance tests (LOCKED) — lab-report demo geometry.

Extends the citation-overlay demo to lab extractions: `demo_geometry` serves
committed word geometry for BOTH the intake form and the lab report (flag-gated),
so a `lab_pdf` extraction returns the per-field `citation_boxes` map locating each
grounded lab value. Deterministic: reads the committed fixture + a monkeypatched
extractor; no OCR, no live API.
"""
import json
import os

import server
from bbox import locate_citation_boxes
from demo_bbox import demo_geometry, intake_demo_geometry

_LAB_GEO = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "documents", "synthetic_lab_geometry.json"
)
_LAB_PDF = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "documents", "synthetic_lab_report_demo.pdf"
)


# --- 1. demo_geometry serves both doc types, gated on the flag ---------------

def test_demo_geometry_serves_lab_for_lab_pdf(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_BBOX_DEMO", "1")
    geom = demo_geometry(1, 42, "lab_pdf")
    assert geom is not None
    assert geom["page_width"] and geom["page_height"]
    assert isinstance(geom["words"], list) and geom["words"]


def test_demo_geometry_serves_intake_for_intake_form(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_BBOX_DEMO", "1")
    assert demo_geometry(1, 42, "intake_form") is not None


def test_demo_geometry_off_by_default(monkeypatch):
    monkeypatch.delenv("OE_AI_AGENT_BBOX_DEMO", raising=False)
    assert demo_geometry(1, 42, "lab_pdf") is None
    assert demo_geometry(1, 42, "intake_form") is None


def test_demo_geometry_none_for_unknown_doc_type(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_BBOX_DEMO", "1")
    assert demo_geometry(1, 42, "radiology") is None


def test_intake_provider_stays_intake_only(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_BBOX_DEMO", "1")
    assert intake_demo_geometry(1, 42, "lab_pdf") is None
    assert intake_demo_geometry(1, 42, "intake_form") is not None


# --- 2. the committed lab fixtures -------------------------------------------

def test_lab_pdf_fixture_exists():
    assert os.path.exists(_LAB_PDF)
    with open(_LAB_PDF, "rb") as handle:
        assert handle.read(5) == b"%PDF-"


def test_lab_geometry_locates_each_lab_value():
    geom = json.load(open(_LAB_GEO))
    words = geom["words"]
    for value in ["Hemoglobin A1c", "7.4", "4.0-5.6", "2026-05-01", "High"]:
        assert locate_citation_boxes(words, value), f"no box located for {value!r}"


# --- 3. a lab extraction yields a per-field citation_boxes map ---------------

class _LabFact:
    def __init__(self):
        self.source_citation = "Hemoglobin A1c"
        self.demographics = None

    def model_dump(self):
        return {
            "test_name": "Hemoglobin A1c",
            "value": "7.4",
            "abnormal_flag": "High",
            "source_citation": "Hemoglobin A1c",
        }


def _fake_lab_result():
    return type(
        "R",
        (),
        {
            "doc_type": "lab_pdf",
            "confidence": 0.93,
            "low_confidence": False,
            "unsupported_fields": [],
            "fact": _LabFact(),
        },
    )()


def test_lab_extract_response_has_per_field_boxes(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_BBOX_DEMO", "1")
    monkeypatch.setattr(server, "build_chart_boundary", lambda *a, **k: object())
    monkeypatch.setattr(server, "attach_and_extract", lambda *a, **k: _fake_lab_result())

    extract = server.default_extract_builder("http://oe/summary.php", None, word_geometry=demo_geometry)
    body = extract(1, "jwt", 5, "lab_pdf")

    cb = body["citation_boxes"]
    assert isinstance(cb, dict) and cb
    geom = json.load(open(_LAB_GEO))
    assert cb["test_name"] == locate_citation_boxes(geom["words"], "Hemoglobin A1c")
    assert cb["value"] == locate_citation_boxes(geom["words"], "7.4")
    assert cb["abnormal_flag"] == locate_citation_boxes(geom["words"], "High")
    assert body["page_width"] == geom["page_width"]
    assert body["page_height"] == geom["page_height"]
