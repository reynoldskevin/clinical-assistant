"""T72a acceptance tests (LOCKED) — per-marker citation sources in /ask.

Makes the answer's ``[Sn]`` markers resolvable to their source: the agent already
maps each surviving marker to a ref + its backing record, so expose that as a
``{marker: {ref, type, section, text}}`` map and return it in the ``/ask`` (and
``/ask/stream``) response for the card (T72b) to render on click.

Deterministic: direct calls to the pure builder + the agent's compose step + a
fake agent through ``process_ask``. No live API, no sockets.
"""
import json

from agent import ClaudeAgent, build_citation_sources
from server import process_ask

RETRIEVED = {
    "guideline:g1": {
        "text": "Target HbA1c below 7 percent for most nonpregnant adults.",
        "citation": "ADA 2024 - Glycemic Targets",
    },
    "prescription:1": {"drug": "Warfarin Sodium 5 MG", "section": "Medications"},
}
CITATIONS = [{"n": 1, "ref": "guideline:g1"}, {"n": 2, "ref": "prescription:1"}]


def _agent():
    return ClaudeAgent(lambda **k: None, lambda p: {}, correlation_id="cid-c")


# --- 1. the pure builder -----------------------------------------------------

def test_build_citation_sources_maps_markers_to_source_content():
    src = build_citation_sources(CITATIONS, RETRIEVED)
    assert src["1"]["ref"] == "guideline:g1"
    assert src["1"]["type"] == "guideline"
    assert "HbA1c" in src["1"]["text"]
    assert src["1"]["section"] == "ADA 2024 - Glycemic Targets"
    assert src["2"]["type"] == "record"
    assert src["2"]["text"] == "Warfarin Sodium 5 MG"


def test_build_citation_sources_omits_refs_with_no_backing_record():
    assert build_citation_sources([{"n": 1, "ref": "prescription:99"}], {}) == {}


# --- 2. the agent exposes them after composing -------------------------------

def test_agent_citation_sources_defaults_empty():
    assert _agent().citation_sources == {}


def test_agent_exposes_citation_sources_after_composition():
    a = _agent()
    rendered = "Warfarin is active [S2]. Target is under 7 percent [S1]."
    a._apply_citation_split(rendered, CITATIONS, {"guideline:g1", "prescription:1"}, RETRIEVED)
    assert set(a.citation_sources.keys()) == {"1", "2"}
    assert a.citation_sources["1"]["type"] == "guideline"
    assert a.citation_sources["2"]["text"] == "Warfarin Sodium 5 MG"


# --- 3. process_ask includes / omits the citations map -----------------------

class _FakeAgent:
    correlation_id = "cid-fake"
    citation_sources = {
        "1": {"ref": "guideline:g1", "type": "guideline", "section": "ADA", "text": "Target under 7%"},
    }
    observer = None

    def run(self, question, pid):
        return "Target is under 7 percent [S1]."


def test_process_ask_includes_citations_in_the_response():
    status, body = process_ask(
        "Bearer jwt", json.dumps({"pid": 1, "question": "q"}).encode(), lambda p, j: _FakeAgent()
    )
    assert status == 200
    assert body["citations"]["1"]["ref"] == "guideline:g1"
    # existing fields untouched
    assert body["answer"] == "Target is under 7 percent [S1]."
    assert body["correlation_id"] == "cid-fake"


def test_process_ask_omits_citations_when_agent_has_none():
    class _A(_FakeAgent):
        citation_sources: dict = {}

    status, body = process_ask(
        "Bearer jwt", json.dumps({"pid": 1, "question": "q"}).encode(), lambda p, j: _A()
    )
    assert status == 200
    assert "citations" not in body
