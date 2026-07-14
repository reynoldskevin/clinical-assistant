"""T50b acceptance tests (LOCKED) — activation: surface the T50 citation gate
(structured citations + record-vs-guideline split) in the LIVE agent answer.

Locked contract (orchestrator-authored, TDD). The implementer:
  * gives ``build_evidence_retriever_tool`` rows a citable ``guideline:<chunk_id>``
    ref so a guideline claim can be grounded and routed;
  * composes ``CitationGate`` into ``ClaudeAgent._gate_final_answer`` AFTER the
    Week-1 ``VerificationGate`` so that, WHEN guideline evidence is cited, the
    returned answer is split into the two T50 sections;
  * leaves the W1 rendering byte-for-byte unchanged when there is no guideline
    evidence (record-only or format-less answers).
Test files must NOT be edited by the implementer.

Offline + deterministic: no Claude, no network, no keys. The message creator is a
scripted fake; the boundary is never called (the scripted model calls only the
injected record tool + the real evidence_retriever over the in-repo corpus).
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent
from citation_gate import GUIDELINE_SECTION_HEADER, RECORD_SECTION_HEADER
from retrieval import build_evidence_retriever_tool, get_guideline_index

_GUIDELINE_QUERY = "warfarin INR target range monitoring"


# --- scripted-creator harness (mirrors tests/test_verification.py) ------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ScriptedCreator:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class RecordingBoundary:
    def __init__(self, summary):
        self.summary = summary

    def __call__(self, pid):
        return self.summary


def _med_spec(rows):
    return {
        "name": "get_medications",
        "description": "get_medications tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": lambda pid, inp: rows,
    }


def _citations_block(pairs):
    return "```citations\n" + json.dumps([{"n": n, "ref": ref} for n, ref in pairs]) + "\n```"


# --- evidence rows are now citable (guideline:<chunk_id> ref) ------------------

def test_evidence_retriever_rows_carry_a_guideline_ref():
    tool = build_evidence_retriever_tool(get_guideline_index())
    rows = tool["handler"](1, {"query": _GUIDELINE_QUERY})
    assert rows, "real retrieval should return rows, not stub-empty"
    for row in rows:
        assert isinstance(row.get("ref"), str)
        assert row["ref"].startswith("guideline:")
    # the existing fields are preserved (activation ADDS a ref, removes nothing)
    assert {"citation", "text", "score"} <= set(rows[0].keys())


def test_collect_refs_captures_the_guideline_ref_end_to_end():
    # Contract / round-trip: the REAL producer output flows into the REAL consumer
    # ref-collection so a guideline [Sn] can be grounded (no hand-faked shape).
    from agent import _collect_refs

    tool = build_evidence_retriever_tool(get_guideline_index())
    rows = tool["handler"](1, {"query": _GUIDELINE_QUERY})
    refs = _collect_refs(rows)
    assert any(r.startswith("guideline:") for r in refs)


# --- the live answer splits record facts from guideline evidence --------------

def _guideline_ref():
    tool = build_evidence_retriever_tool(get_guideline_index())
    rows = tool["handler"](1, {"query": _GUIDELINE_QUERY})
    return rows[0]["ref"]


def test_live_answer_splits_record_and_guideline_sections():
    gref = _guideline_ref()
    final = (
        "The patient is on Warfarin 5 mg [S1]. "
        "Guideline target INR is 2.0-3.0 for atrial fibrillation [S2].\n"
        + _citations_block([(1, "prescription:1"), (2, gref)])
    )
    creator = ScriptedCreator([
        _resp(
            [
                _tool_use("get_medications", {}, "t1"),
                _tool_use("evidence_retriever", {"query": _GUIDELINE_QUERY}, "t2"),
            ],
            "tool_use",
        ),
        _resp([_text(final)], "end_turn"),
    ])
    med = _med_spec([{"ref": "prescription:1", "drug": "Warfarin", "active": True}])
    evidence = build_evidence_retriever_tool(get_guideline_index())
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[med, evidence])

    answer = agent.run("warfarin dosing and target INR?", pid=1)

    # both distinct section markers present, record section first
    assert RECORD_SECTION_HEADER in answer
    assert GUIDELINE_SECTION_HEADER in answer
    assert answer.index(RECORD_SECTION_HEADER) < answer.index(GUIDELINE_SECTION_HEADER)

    record_part = answer[answer.index(RECORD_SECTION_HEADER):answer.index(GUIDELINE_SECTION_HEADER)]
    guideline_part = answer[answer.index(GUIDELINE_SECTION_HEADER):]
    low_rec, low_gl = record_part.lower(), guideline_part.lower()

    # the record med claim lands under the record section, not the guideline one
    assert "on warfarin 5 mg" in low_rec
    assert "on warfarin 5 mg" not in low_gl
    # the guideline claim lands under the guideline section, not the record one
    assert "guideline target inr is 2.0-3.0" in low_gl
    assert "guideline target inr is 2.0-3.0" not in low_rec


# --- record-only citations degrade to the W1 rendering (no split) -------------

def test_record_only_answer_keeps_w1_rendering_and_adds_no_section_headers():
    final = "The patient is on Warfarin 5 mg [S1].\n" + _citations_block([(1, "prescription:1")])
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text(final)], "end_turn"),
    ])
    med = _med_spec([{"ref": "prescription:1", "drug": "Warfarin", "active": True}])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[med])

    answer = agent.run("what warfarin dose?", pid=1)

    # no guideline evidence -> nothing to separate -> W1 rendering is preserved
    assert GUIDELINE_SECTION_HEADER not in answer
    assert RECORD_SECTION_HEADER not in answer
    assert "```citations" not in answer          # block still stripped (W1)
    assert "[S1]" in answer                       # valid marker kept (W1)
    assert answer == "The patient is on Warfarin 5 mg [S1]."


# --- format-less answer is returned unchanged (back-compat) -------------------

def test_format_less_answer_is_unchanged():
    creator = ScriptedCreator([_resp([_text("Your blood pressure is 120/80.")], "end_turn")])
    agent = ClaudeAgent(creator, RecordingBoundary({}))
    assert agent.run("bp?", pid=1) == "Your blood pressure is 120/80."
