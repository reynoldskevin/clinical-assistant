"""T83 acceptance tests (LOCKED) — deterministic inline guideline grounding.

Guideline chips were intermittent: a guideline reached the card's
``citation_sources`` map only when the model declared it in the fenced
```citations block with an ``[Sn]`` number. When the model instead inlined the
raw ``[guideline:<ref>]`` marker (which the prompt permits), the ref never
entered the map and the citation was lost. These tests pin that ANY inline
``[guideline:<ref>]`` marker whose ref was actually retrieved this turn is
resolved into ``citation_sources`` — keyed by the exact ref, type ``guideline``,
with the chunk's title/snippet — regardless of the citations block, while a
cited-but-not-retrieved ref is never fabricated. Grounding becomes a pure
function of (answer text, retrieved data), so it is deterministic.

Deterministic/offline: scripted model, fake evidence tool + boundary. No SDK,
no network, no key.
"""
from types import SimpleNamespace

from agent import ClaudeAgent


# --- scripted model + fakes ---------------------------------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks):
    return SimpleNamespace(content=blocks, stop_reason="end_turn", usage=None)


class ScriptedCreator:
    def __init__(self, responses):
        self._responses = list(responses)

    def __call__(self, **kwargs):
        return self._responses.pop(0)


def _boundary(pid):
    # A summary with no citable refs — the guideline/record refs come from tools.
    return {"problems": []}


def _tool(name, rows):
    def handler(pid, inp):
        return list(rows)

    return {
        "name": name,
        "description": name,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "additionalProperties": True,
        },
        "handler": handler,
    }


# The retrieved guideline chunk (exactly the shape evidence_retriever emits).
GREF = "guideline:diabetes:glycemic-targets"
GROW = {
    "ref": GREF,
    "citation": "Diabetes Guideline - Glycemic Targets",
    "text": "A reasonable HbA1c goal is below 7.0%.",
    "score": 0.9,
}

# An empty citations block: the model inlined the guideline but declared nothing.
_EMPTY_BLOCK = "\n\n```citations\n[]\n```"


def _run_inline_guideline_turn(answer_text=None):
    """Run one turn: retrieve the guideline chunk, then answer inlining GREF."""
    answer = answer_text or ("A reasonable HbA1c goal is below 7.0% [" + GREF + "].")
    creator = ScriptedCreator([
        _resp([_tool_use("evidence_retriever", {"query": "hba1c targets"}, "e1")]),
        _resp([_text(answer + _EMPTY_BLOCK)]),
    ])
    agent = ClaudeAgent(creator, _boundary, extra_tools=[_tool("evidence_retriever", [GROW])])
    agent.run("what are the guideline targets?", pid=1)
    return agent


# --- AC1 + AC5: an inline, retrieved guideline ref is grounded, keyed by ref ---

def test_inline_guideline_marker_is_grounded_into_citation_sources():
    agent = _run_inline_guideline_turn()

    assert GREF in agent.citation_sources, agent.citation_sources
    entry = agent.citation_sources[GREF]
    assert entry["type"] == "guideline"
    assert entry["ref"] == GREF
    assert entry["section"] == "Diabetes Guideline - Glycemic Targets"
    assert entry["text"] == "A reasonable HbA1c goal is below 7.0%."


# --- AC2: a cited guideline ref that was NOT retrieved is never fabricated -----

def test_unretrieved_guideline_ref_is_not_added():
    answer = (
        "A reasonable HbA1c goal is below 7.0% [" + GREF + "]. "
        "Blood pressure below 130/80 [guideline:htn:bp-target]."
    )
    agent = _run_inline_guideline_turn(answer_text=answer)

    assert GREF in agent.citation_sources                       # retrieved -> grounded
    assert "guideline:htn:bp-target" not in agent.citation_sources  # not retrieved -> absent


# --- AC3: grounding is deterministic across identical runs ---------------------

def test_grounding_is_deterministic_across_runs():
    a1 = _run_inline_guideline_turn()
    a2 = _run_inline_guideline_turn()
    assert a1.citation_sources == a2.citation_sources
    assert GREF in a1.citation_sources


# --- AC4: a declared record [Sn] still grounds alongside the inline guideline --

def test_record_marker_still_grounds_alongside_inline_guideline():
    med_row = {"ref": "prescription:1", "drug": "Warfarin Sodium 5 MG"}
    answer = (
        "Warfarin Sodium 5 MG is active [S1]. "
        "A reasonable HbA1c goal is below 7.0% [" + GREF + "].\n\n"
        '```citations\n[{"n": 1, "ref": "prescription:1"}]\n```'
    )
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "m1")]),
        _resp([_tool_use("evidence_retriever", {"query": "x"}, "e1")]),
        _resp([_text(answer)]),
    ])
    agent = ClaudeAgent(
        creator,
        _boundary,
        extra_tools=[_tool("get_medications", [med_row]), _tool("evidence_retriever", [GROW])],
    )
    agent.run("meds and guideline?", pid=1)

    # record citation still keyed by marker number, type record
    assert "1" in agent.citation_sources, agent.citation_sources
    assert agent.citation_sources["1"]["type"] == "record"
    # inline guideline resolved keyed by ref, type guideline
    assert GREF in agent.citation_sources
    assert agent.citation_sources[GREF]["type"] == "guideline"
