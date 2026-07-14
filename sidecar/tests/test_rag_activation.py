"""Acceptance tests for ticket 49b — activation: wire the evidence_retriever
guideline-RAG tool into the live Co-Pilot agent.

Locked contract (orchestrator-authored, TDD). The implementer wires the tool into
``server.default_agent_builder`` and adds a build-once guideline-index singleton
``retrieval.get_guideline_index`` (cached in the module global ``_GUIDELINE_INDEX``).
Test files must NOT be edited by the implementer.

Offline + deterministic: no Claude, no network, no keys. The message creator is a
scripted fake; the boundary is never called (the scripted model only invokes the
evidence_retriever tool, which reads the in-repo guideline corpus).
"""

import json
from types import SimpleNamespace

import retrieval
from retrieval import get_guideline_index
from server import default_agent_builder


# --- scripted-creator harness (mirrors tests/test_agent.py) -------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ScriptedCreator:
    """Fake message-creator: returns scripted responses, records call kwargs."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _tool_results(messages):
    """Collect tool_result blocks from a message history (user turns)."""
    out = []
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out.append(block)
    return out


SUMMARY_URL = "http://openemr/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php"


# --- build-once guideline index singleton ------------------------------------

def test_get_guideline_index_builds_once_and_is_reused(monkeypatch):
    calls = {"n": 0}
    real_build = retrieval.build_index

    def counting_build(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    # Reset the cache and count real builds.
    retrieval._GUIDELINE_INDEX = None
    monkeypatch.setattr(retrieval, "build_index", counting_build)

    a = get_guideline_index()
    b = get_guideline_index()

    assert a is b                # same object reused, not rebuilt
    assert calls["n"] == 1       # built exactly once
    assert len(a.chunks) == 9    # it is the real committed corpus


# --- the live agent offers the evidence_retriever tool -----------------------

def test_default_agent_builder_offers_evidence_retriever_alongside_chart_tools():
    creator = ScriptedCreator([
        _resp([_tool_use("evidence_retriever", {"query": "warfarin INR"}, "t1")], "tool_use"),
        _resp([_text("done")], "end_turn"),
    ])
    builder = default_agent_builder(SUMMARY_URL, creator)
    agent = builder(1, "jwt-token")
    agent.run("anything", pid=1)

    offered = {t["name"] for t in creator.calls[0]["tools"]}
    assert "evidence_retriever" in offered
    # the existing chart tools are still offered (activation only ADDS a tool)
    assert {"get_results", "get_medications", "search_chart", "get_documents"} <= offered


# --- end-to-end: guideline question -> cited rows + traced hits ---------------

def test_evidence_retriever_returns_cited_guideline_rows_and_logs_hits():
    creator = ScriptedCreator([
        _resp([_tool_use("evidence_retriever", {"query": "warfarin INR target range monitoring"}, "t1")], "tool_use"),
        _resp([_text("Target INR is 2.0-3.0 for atrial fibrillation.")], "end_turn"),
    ])
    builder = default_agent_builder(SUMMARY_URL, creator)
    agent = builder(1, "jwt-token")

    answer = agent.run("What INR range for warfarin?", pid=1)
    assert answer.startswith("Target INR is 2.0-3.0")

    # the tool_result fed back to the model carries cited guideline rows
    results = _tool_results(creator.calls[1]["messages"])
    blob = "".join(
        (tr["content"] if isinstance(tr["content"], str) else json.dumps(tr["content"]))
        for tr in results
    )
    assert "Warfarin INR Monitoring" in blob  # real retrieval, not stub-empty

    # retrieval hits + scores are recorded on THIS turn's TraceCollector
    hits = agent.observer.summary()["retrieval_hits"]
    assert hits
    assert any("Warfarin INR Monitoring" in h["citation"] for h in hits)
    assert all("score" in h for h in hits)


# --- the index is not rebuilt per request ------------------------------------

def test_index_is_not_rebuilt_per_request(monkeypatch):
    calls = {"n": 0}
    real_build = retrieval.build_index

    def counting_build(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    retrieval._GUIDELINE_INDEX = None
    monkeypatch.setattr(retrieval, "build_index", counting_build)

    creator = ScriptedCreator([
        _resp([_text("hi")], "end_turn"),
        _resp([_text("hi")], "end_turn"),
    ])
    builder = default_agent_builder(SUMMARY_URL, creator)
    # Two separate requests / agent builds.
    builder(1, "jwt-a")
    builder(2, "jwt-b")

    assert calls["n"] == 1  # index built once for the whole process, not per /ask
