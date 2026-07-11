"""T23 acceptance tests (LOCKED) — verification gate: grounding (V1 + V2).

The gate is deterministic and tested directly; the agent applies it to answers
that use the grounding format, and passes format-less answers through unchanged.
No anthropic SDK, no live API call.
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent
from verification import VerificationGate


# --- V1/V2 gate (pure) ---------------------------------------------------------

def test_pass_when_a_numeric_claim_carries_a_valid_citation():
    v = VerificationGate().verify(
        "Patient is on Warfarin 5 mg [S1].",
        [{"n": 1, "ref": "prescription:1"}],
        {"prescription:1"},
    )
    assert v["verdict"] == "pass"
    assert v["flags"] == []
    assert v["rendered_answer"] == "Patient is on Warfarin 5 mg [S1]."


def test_v1_fabricated_citation_is_stripped_and_flagged():
    v = VerificationGate().verify(
        "On Warfarin 5 mg [S1] and Metformin 500 mg [S2].",
        [{"n": 1, "ref": "prescription:1"}, {"n": 2, "ref": "prescription:999"}],
        {"prescription:1"},
    )
    assert v["verdict"] == "pass_with_flags"
    assert any(f["code"] == "fabricated_citation" and f.get("ref") == "prescription:999" for f in v["flags"])
    assert "[S2]" not in v["rendered_answer"]   # fabricated marker stripped
    assert "[S1]" in v["rendered_answer"]        # valid marker kept


def test_v2_ungrounded_numeric_claim_is_demoted():
    v = VerificationGate().verify(
        "The glucose was 180 mg/dL.",
        [],
        set(),
    )
    assert v["verdict"] == "pass_with_flags"
    assert any(f["code"] == "ungrounded_claim" for f in v["flags"])
    assert "not supported by the record" in v["rendered_answer"]


def test_absence_ref_is_a_valid_citation():
    v = VerificationGate().verify(
        "There is no HbA1c value on file [S1].",
        [{"n": 1, "ref": "openemr:_absence"}],
        set(),
    )
    assert v["verdict"] == "pass"
    assert v["flags"] == []


def test_non_assertion_and_grounded_numeric_sentences_produce_no_flags():
    gate = VerificationGate()
    non = gate.verify("How can I help you today?", [], set())
    assert non["verdict"] == "pass" and non["flags"] == []

    grounded = gate.verify("The BP is 120/80 [S1].", [{"n": 1, "ref": "vital:1"}], {"vital:1"})
    assert grounded["verdict"] == "pass" and grounded["flags"] == []


def test_verdict_has_the_documented_schema():
    v = VerificationGate().verify("Hello.", [], set())
    assert set(v.keys()) >= {"verdict", "flags", "rendered_answer"}
    assert v["verdict"] in {"pass", "pass_with_flags", "blocked"}


# --- agent integration ---------------------------------------------------------

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


def _spec(name, handler):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


def test_agent_gates_a_formatted_answer_and_strips_the_citations_block():
    block = "```citations\n" + json.dumps(
        [{"n": 1, "ref": "prescription:1"}, {"n": 2, "ref": "prescription:999"}]
    ) + "\n```"
    final = "The patient is on Warfarin 5 mg [S1]. The glucose was 180 mg/dL [S2].\n" + block

    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text(final)], "end_turn"),
    ])
    med = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[med])

    answer = agent.run("what meds is the patient on?", pid=42)

    assert "```citations" not in answer                 # citations block removed from user-facing text
    assert "[S1]" in answer                              # valid citation kept
    assert "[S2]" not in answer                          # prescription:999 fabricated -> stripped (V1)
    assert "not supported by the record" in answer       # the now-uncited glucose claim demoted (V2)


def test_agent_returns_a_format_less_answer_unchanged():
    # No citations block -> the gate does not apply -> answer unchanged (back-compat
    # with T12/T17/T21/T22, whose scripted answers contain digits like "120/80").
    creator = ScriptedCreator([_resp([_text("Your blood pressure is 120/80.")], "end_turn")])
    agent = ClaudeAgent(creator, RecordingBoundary({}))
    assert agent.run("bp?", pid=42) == "Your blood pressure is 120/80."


# --- decimal clinical values must not be mis-split (regression) ---

def test_grounded_decimal_value_is_not_split_or_falsely_demoted():
    # "2.5" must not be split at the decimal point into a bogus "…2." sentence.
    v = VerificationGate().verify(
        "The INR was 2.5 [S1].",
        [{"n": 1, "ref": "result:1"}],
        {"result:1"},
    )
    assert v["verdict"] == "pass"
    assert v["flags"] == []
    assert v["rendered_answer"] == "The INR was 2.5 [S1]."


def test_ungrounded_decimal_claim_is_demoted_without_corrupting_the_value():
    v = VerificationGate().verify("The HbA1c was 6.5%.", [], set())
    assert v["verdict"] == "pass_with_flags"
    assert any(f["code"] == "ungrounded_claim" for f in v["flags"])
    assert "not supported by the record" in v["rendered_answer"]
    assert "6.5" in v["rendered_answer"]  # the decimal value is preserved, not mangled to "6 (...).5"
