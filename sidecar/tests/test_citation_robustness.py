"""T64 acceptance tests (LOCKED) — citation robustness.

Deferred from T50. The CitationGate validated a claim's five-field Citation and
routed it record-vs-guideline, but never checked that the citation's
`quote_or_value` was actually grounded in the cited source — a fabricated /
mismatched quote was routed as a clean grounded fact. T64 adds an OPT-IN
quote-grounding check whose failure is a SOFT demote (not a hard block): an
unverifiable quote is a grounding weakness (downgrade the claim, keep the answer),
distinct from V3's hard block for a factual contradiction.

Backward compatible: `gate(claims)` with no `sources` behaves exactly as before.

Unit tests only: pure gate + a white-box wiring check on the agent split — no
anthropic SDK, no network.
"""
from citation_gate import (
    GUIDELINE_SECTION_HEADER,
    QUOTE_MISMATCH_NOTE,
    SOURCE_GUIDELINE,
    SOURCE_RECORD,
    CitationGate,
)


def _record_citation(**over):
    base = {
        "source_type": SOURCE_RECORD,
        "source_id": "prescription:1",
        "page_or_section": "Medications",
        "field_or_chunk_id": "drug",
        "quote_or_value": "Warfarin 5 mg",
    }
    base.update(over)
    return base


def _guideline_citation(**over):
    base = {
        "source_type": SOURCE_GUIDELINE,
        "source_id": "guideline:afib_anticoagulation:target-inr",
        "page_or_section": "Anticoagulation",
        "field_or_chunk_id": "afib_anticoagulation:target-inr",
        "quote_or_value": "target INR 2.0-3.0",
    }
    base.update(over)
    return base


# --- backward compatibility --------------------------------------------------

def test_gate_without_sources_matches_sources_none():
    claims = [{"text": "On Warfarin 5 mg.", "citation": _record_citation()}]
    assert CitationGate().gate(claims) == CitationGate().gate(claims, sources=None)


def test_no_sources_preserves_routing_and_no_flags():
    result = CitationGate().gate(
        [
            {"text": "On Warfarin 5 mg.", "citation": _record_citation()},
            {"text": "Target INR is 2-3.", "citation": _guideline_citation()},
        ]
    )
    assert result["verdict"] == "pass"
    assert result["flags"] == []
    assert any("Warfarin" in f for f in result["record_facts"])
    assert any("Target INR" in e for e in result["guideline_evidence"])


# --- grounded quotes pass ----------------------------------------------------

def test_grounded_record_quote_passes():
    sources = {"prescription:1": "Warfarin 5 mg oral tablet, active"}
    result = CitationGate().gate(
        [{"text": "On Warfarin.", "citation": _record_citation(quote_or_value="Warfarin")}],
        sources=sources,
    )
    assert result["verdict"] == "pass"
    assert result["flags"] == []
    assert any("On Warfarin." == f for f in result["record_facts"])


def test_grounded_guideline_quote_passes():
    sources = {
        "guideline:afib_anticoagulation:target-inr":
            "For atrial fibrillation, maintain INR between 2.0 and 3.0.",
    }
    result = CitationGate().gate(
        [{"text": "Target INR is 2-3.", "citation": _guideline_citation(quote_or_value="INR between 2.0 and 3.0")}],
        sources=sources,
    )
    assert result["flags"] == []
    assert any("Target INR" in e for e in result["guideline_evidence"])


def test_quote_match_is_case_and_whitespace_insensitive():
    sources = {"prescription:1": "   warfarin   5   MG  "}
    result = CitationGate().gate(
        [{"text": "x", "citation": _record_citation(quote_or_value="Warfarin 5 mg")}],
        sources=sources,
    )
    assert result["flags"] == []


def test_partial_quote_is_grounded_in_either_direction():
    # quote shorter than the source field
    shorter = CitationGate().gate(
        [{"text": "x", "citation": _record_citation(quote_or_value="Warfarin")}],
        sources={"prescription:1": "Warfarin 5 mg"},
    )
    # quote longer than the source field
    longer = CitationGate().gate(
        [{"text": "x", "citation": _record_citation(quote_or_value="Warfarin 5 mg")}],
        sources={"prescription:1": "Warfarin"},
    )
    assert shorter["flags"] == []
    assert longer["flags"] == []


# --- ungrounded quote is DEMOTED, never blocked ------------------------------

def test_fabricated_record_quote_is_demoted_not_blocked():
    sources = {"prescription:1": "Warfarin 5 mg"}
    result = CitationGate().gate(
        [{"text": "On Aspirin.", "citation": _record_citation(quote_or_value="Aspirin 81 mg")}],
        sources=sources,
    )
    assert result["verdict"] == "pass_with_flags"
    assert result["verdict"] != "blocked"
    assert any(
        f["code"] == "quote_mismatch" and f.get("source_id") == "prescription:1"
        for f in result["flags"]
    )
    # demoted: kept OUT of the clean record bucket, but still shown (marked) in the answer
    assert not any("Aspirin" in f for f in result["record_facts"])
    assert "On Aspirin." + QUOTE_MISMATCH_NOTE in result["rendered_answer"]


def test_fabricated_guideline_quote_is_demoted():
    sources = {"guideline:afib_anticoagulation:target-inr": "maintain INR between 2.0 and 3.0"}
    result = CitationGate().gate(
        [{"text": "Target INR is 5-7.", "citation": _guideline_citation(quote_or_value="target INR 5.0-7.0")}],
        sources=sources,
    )
    assert result["verdict"] == "pass_with_flags"
    assert any(f["code"] == "quote_mismatch" for f in result["flags"])
    assert not any("Target INR" in e for e in result["guideline_evidence"])


def test_source_absent_from_map_is_not_quote_checked():
    # The source for this citation is not supplied, so the gate cannot verify the
    # quote — it must NOT demote (no false positive).
    sources = {"prescription:99": "Metformin 500 mg"}
    result = CitationGate().gate(
        [{"text": "On Aspirin.", "citation": _record_citation(quote_or_value="Aspirin")}],
        sources=sources,
    )
    assert result["verdict"] == "pass"
    assert result["flags"] == []
    assert any("On Aspirin." == f for f in result["record_facts"])


def test_mixed_grounded_and_fabricated_only_demotes_the_bad_one():
    sources = {
        "prescription:1": "Warfarin 5 mg",
        "prescription:2": "Metformin 500 mg",
    }
    result = CitationGate().gate(
        [
            {"text": "On Warfarin.", "citation": _record_citation(quote_or_value="Warfarin")},
            {"text": "On Lisinopril.", "citation": _record_citation(source_id="prescription:2", quote_or_value="Lisinopril 10 mg")},
        ],
        sources=sources,
    )
    assert result["verdict"] == "pass_with_flags"
    assert any("On Warfarin." == f for f in result["record_facts"])
    assert not any("Lisinopril" in f for f in result["record_facts"])
    assert sum(1 for f in result["flags"] if f["code"] == "quote_mismatch") == 1


# --- live wiring: the agent split passes record sources into the gate ---------

def test_apply_citation_split_passes_sources_from_retrieved_data(monkeypatch):
    import citation_gate

    captured = {}
    real_gate = citation_gate.CitationGate.gate

    def spy(self, claims, sources=None):
        captured["sources"] = sources
        return real_gate(self, claims, sources=sources)

    monkeypatch.setattr(citation_gate.CitationGate, "gate", spy)

    from agent import ClaudeAgent

    agent = ClaudeAgent(lambda **kwargs: None, lambda pid: {})
    rendered = "On Warfarin [S1]. Target INR is 2-3 [S2]."
    citations = [
        {"n": 1, "ref": "prescription:1"},
        {"n": 2, "ref": "guideline:afib_anticoagulation:target-inr"},
    ]
    retrieved_refs = {"prescription:1", "guideline:afib_anticoagulation:target-inr"}
    retrieved_data = {
        "prescription:1": {"ref": "prescription:1", "drug": "Warfarin", "active": True},
        "guideline:afib_anticoagulation:target-inr": {
            "ref": "guideline:afib_anticoagulation:target-inr",
            "text": "target INR 2.0-3.0",
            "citation": "AFib anticoagulation guideline",
        },
    }

    # A guideline ref is present, so the split activates and gate() is called.
    agent._apply_citation_split(rendered, citations, retrieved_refs, retrieved_data)

    assert captured.get("sources") is not None
    assert "prescription:1" in captured["sources"]
    assert "warfarin" in captured["sources"]["prescription:1"].lower()
