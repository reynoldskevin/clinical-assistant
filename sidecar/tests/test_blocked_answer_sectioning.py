"""T50c regression test (LOCKED) — a BLOCKED answer must never be sectioned.

When the Week-1 verification gate BLOCKS a draft (V3/V6/V7), it returns the safe
fallback in place of the unverified draft. The T50b citation split must NOT run
on that fallback: the original citations list still carries a ``guideline:`` ref,
so without a guard the fallback got wrapped under a ``## Patient record`` header
(cosmetic leak of the split machinery onto a blocked answer). This pins the fix:
a blocked verdict is returned as the plain safe fallback, no section headers.

Offline + deterministic: no Claude, no network. The scripted model calls a record
tool + the real evidence_retriever (so a guideline ref really is grounded this
turn), then emits a final answer that trips V6 (an SSN leak) -> W1 blocks.
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent
from citation_gate import GUIDELINE_SECTION_HEADER, RECORD_SECTION_HEADER
from retrieval import build_evidence_retriever_tool, get_guideline_index

_GUIDELINE_QUERY = "warfarin INR target range monitoring"


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


def _guideline_ref():
    tool = build_evidence_retriever_tool(get_guideline_index())
    return tool["handler"](1, {"query": _GUIDELINE_QUERY})[0]["ref"]


def test_blocked_answer_is_not_sectioned_even_with_guideline_evidence():
    gref = _guideline_ref()
    # The SSN in the draft trips V6 (identifier leak) -> W1 BLOCKS -> safe fallback.
    # The citations still include a guideline ref, which (pre-fix) drove the split.
    final = (
        "The patient SSN 123-45-6789 is on Warfarin 5 mg [S1]. "
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

    answer = agent.run("warfarin and INR?", pid=1)

    # A blocked answer is the plain safe fallback — never sectioned.
    assert RECORD_SECTION_HEADER not in answer
    assert GUIDELINE_SECTION_HEADER not in answer
    # The safe fallback stands in for the draft; the unverified content is gone.
    assert "verify" in answer.lower()
    assert "123-45-6789" not in answer          # the leaked SSN never surfaces
    assert "Guideline target INR" not in answer  # the unverified draft is not shown


def test_blocked_answer_without_guideline_evidence_still_returns_fallback():
    # Same block via V6, but record-only citations. This path was already correct
    # (no guideline ref -> no split); pinned so the fix doesn't regress it.
    final = (
        "The patient SSN 123-45-6789 is on Warfarin 5 mg [S1].\n"
        + _citations_block([(1, "prescription:1")])
    )
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text(final)], "end_turn"),
    ])
    med = _med_spec([{"ref": "prescription:1", "drug": "Warfarin", "active": True}])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[med])

    answer = agent.run("warfarin?", pid=1)

    assert RECORD_SECTION_HEADER not in answer
    assert "verify" in answer.lower()
    assert "123-45-6789" not in answer
