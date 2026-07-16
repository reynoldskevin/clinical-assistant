"""T67 regression guard — intake-tool facts are grounded record evidence.

Context: T67 was filed 2026-07-15 reporting that the verification gate hedged
``get_intake_form`` facts as "(not supported by the record)" *even when correctly
cited* — the premise being that the gate treated only structured chart reads as
"the record" and not tool-derived intake facts. Investigation showed the gate
never actually discriminated by ref *source*: it grounds any sentence whose
``[Sn]`` marker resolves to a ref that was retrieved this turn, and intake rows
carry a citable ``intake:<document_id>:<field>`` ref that flows into
``retrieved_refs`` like any chart ref (wired by ``7fa9e39``). The live symptom —
an intake numeric sentence the model left *uncited* getting demoted — was fixed
at the prompt layer (``1acceca`` requires a marker on every dated/numeric
sentence), not by changing the gate.

These tests pin that resolved behavior so it cannot silently regress:

* a correctly-cited intake fact passes V1/V2 clean, with no hedge — at both the
  pure-gate level and end-to-end through the live agent;
* the citation split routes an intake fact into the RECORD side, never the
  guideline side;
* the gate still (correctly) demotes an *uncited* numeric intake sentence — the
  fix must not weaken V2 by special-casing intake refs.

Offline + deterministic: no Claude, no network, no keys. The message creator is a
scripted fake and the intake tool is a stub returning the real row shape
(``{ref, title, section, value}``) that ``factory.build_intake_tool`` produces.
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent
from citation_gate import GUIDELINE_SECTION_HEADER
from verification import VerificationGate

# The real ref shape a get_intake_form row carries (factory.build_intake_tool).
_INTAKE_REF = "intake:502:chief_concern"
# The chief-concern as the intake row stores it (a full value, trailing period).
_INTAKE_VALUE = "Intermittent chest tightness and shortness of breath for 2 weeks."
# The same concern as a clause the model embeds mid-sentence — no terminal
# period, so the [Sn] marker sits INSIDE the numeric sentence (correct citation
# placement, per the 1acceca prompt rule) rather than after it.
_INTAKE_CLAUSE = "intermittent chest tightness and shortness of breath for 2 weeks"


# --- pure gate: an intake ref grounds a numeric claim exactly like a chart ref -

def test_cited_intake_numeric_fact_passes_the_gate_clean():
    v = VerificationGate().verify(
        f"The patient's chief concern is {_INTAKE_CLAUSE} [S1].",
        [{"n": 1, "ref": _INTAKE_REF}],
        {_INTAKE_REF},
    )
    assert v["verdict"] == "pass"
    assert v["flags"] == []
    assert "not supported by the record" not in v["rendered_answer"]
    assert "[S1]" in v["rendered_answer"]


def test_uncited_intake_numeric_fact_is_still_demoted():
    # The fix must NOT special-case intake refs: an uncited numeric sentence is
    # genuinely ungrounded and V2 must still flag it, whatever its subject.
    v = VerificationGate().verify(
        f"The patient's chief concern is {_INTAKE_CLAUSE}.",
        [{"n": 1, "ref": _INTAKE_REF}],
        {_INTAKE_REF},
    )
    assert v["verdict"] == "pass_with_flags"
    assert any(f["code"] == "ungrounded_claim" for f in v["flags"])
    assert "not supported by the record" in v["rendered_answer"]


# --- scripted-creator harness (mirrors tests/test_citation_activation.py) ------

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


def _boundary(pid):
    return {}


def _intake_spec():
    """Stub get_intake_form returning the real citable-row shape."""
    rows = [
        {
            "ref": _INTAKE_REF,
            "title": "chief_concern",
            "section": "Intake form",
            "value": _INTAKE_VALUE,
        }
    ]
    return {
        "name": "get_intake_form",
        "description": "get_intake_form tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": lambda pid, inp: rows,
    }


def _citations_block(pairs):
    return "```citations\n" + json.dumps([{"n": n, "ref": ref} for n, ref in pairs]) + "\n```"


# --- end-to-end: the live intake answer reads clean, under the record side -----

def test_live_intake_answer_is_grounded_and_not_hedged():
    final = (
        f"The patient's chief concern is {_INTAKE_CLAUSE} [S1].\n"
        + _citations_block([(1, _INTAKE_REF)])
    )
    creator = ScriptedCreator([
        _resp([_tool_use("get_intake_form", {}, "t1")], "tool_use"),
        _resp([_text(final)], "end_turn"),
    ])
    agent = ClaudeAgent(creator, _boundary, extra_tools=[_intake_spec()])

    answer = agent.run("what is the patient's concern?", pid=1)

    # the intake fact is grounded: no demotion hedge, marker survives
    assert "not supported by the record" not in answer
    assert "[S1]" in answer
    assert "chest tightness" in answer.lower()
    # record-only citation -> no spurious guideline split section
    assert GUIDELINE_SECTION_HEADER not in answer
