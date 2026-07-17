"""T59a acceptance tests (LOCKED) — DASHBOARD.md documents the Week-2 panels.

`DASHBOARD.md` shipped with the Week-1 Braintrust charts. This ticket adds a
Week-2 panels section naming the five panels (§7) and mapping each to its backing
T57 structured event(s)/field(s). Static-text guard, mirrors test_architecture_doc.py.
"""
import os
import re

_HERE = os.path.dirname(__file__)
DOC = os.path.join(_HERE, "..", "DASHBOARD.md")


def _norm() -> str:
    with open(DOC) as fh:
        return re.sub(r"\s+", " ", fh.read().lower())


def _has_any(text, options):
    return any(o in text for o in options)


def test_week2_panels_section_present():
    n = _norm()
    assert _has_any(n, ["week-2 panels", "week 2 panels"]), "no Week-2 panels section heading"


def test_all_five_panels_named():
    n = _norm()
    assert "ingestion" in n
    assert _has_any(n, ["field-level pass rate", "field pass rate", "extraction field"])
    assert _has_any(n, ["retrieval hit rate", "hit rate"])
    assert "routing" in n
    assert _has_any(n, ["per category", "per-category", "by category"])


def test_panels_map_to_their_backing_events():
    n = _norm()
    # each panel's backing T57 event must be named so the mapping is documented
    for event in ("ingestion.complete", "extraction.field", "retrieval.hit", "worker.handoff", "eval.run"):
        assert event in n, f"DASHBOARD.md Week-2 section does not reference {event}"
