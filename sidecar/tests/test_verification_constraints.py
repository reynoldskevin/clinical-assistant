"""T24 acceptance tests (LOCKED) — verification gate constraints V3 + V6.

V3 (contradiction) and V6 (patient scope) are BLOCKING checks: a blocked verdict
replaces the draft with a safe fallback. V4/V5 are deferred (clinical sign-off).
Deterministic; no anthropic SDK, no live API call.
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent
from verification import VerificationGate


# --- V3: contradiction (cited med/allergy must be that record) -----------------

def test_v3_cited_med_matching_the_record_is_fine():
    v = VerificationGate().verify(
        "The patient is on Warfarin [S1].",
        [{"n": 1, "ref": "prescription:1"}],
        {"prescription:1"},
        {"prescription:1": {"drug": "Warfarin"}},
    )
    assert v["verdict"] == "pass"
    assert v["rendered_answer"] == "The patient is on Warfarin [S1]."


def test_v3_misattributed_med_is_blocked():
    v = VerificationGate().verify(
        "The patient is on Aspirin [S1].",
        [{"n": 1, "ref": "prescription:1"}],
        {"prescription:1"},
        {"prescription:1": {"drug": "Warfarin"}},   # cited ref is actually Warfarin
    )
    assert v["verdict"] == "blocked"
    assert any(f["code"] == "contradicts_record" and f.get("ref") == "prescription:1" for f in v["flags"])
    # the unverified draft is never shown; a safe fallback is
    assert "Aspirin" not in v["rendered_answer"]
    assert "verify" in v["rendered_answer"].lower()


def test_v3_only_applies_to_med_allergy_refs():
    # A note citation (pnote:) is not a med/allergy, so V3 does not fire.
    v = VerificationGate().verify(
        "The patient was seen for chest pain [S1].",
        [{"n": 1, "ref": "pnote:1"}],
        {"pnote:1"},
        {"pnote:1": {"snippet": "chest pain"}},
    )
    assert v["verdict"] != "blocked"


# --- V6: patient scope / identifier leak ---------------------------------------

def test_v6_ssn_pattern_is_blocked():
    v = VerificationGate().verify("The patient's SSN is 123-45-6789.", [], set())
    assert v["verdict"] == "blocked"
    assert any(f["code"] == "out_of_scope_phi" for f in v["flags"])
    assert "123-45-6789" not in v["rendered_answer"]
    assert "verify" in v["rendered_answer"].lower()


def test_v6_mrn_identifier_is_blocked():
    v = VerificationGate().verify("See MRN 998877 for the full chart.", [], set())
    assert v["verdict"] == "blocked"
    assert any(f["code"] == "out_of_scope_phi" for f in v["flags"])


def test_v6_clean_answer_is_not_blocked():
    v = VerificationGate().verify("The patient is stable.", [], set())
    assert v["verdict"] == "pass"
    assert v["flags"] == []


# --- precedence + safe fallback ------------------------------------------------

def test_block_takes_precedence_over_pass_with_flags():
    # An ungrounded numeric claim (V2 -> pass_with_flags) AND an SSN (V6 -> block):
    # the block wins and the draft is replaced.
    v = VerificationGate().verify("Glucose was 180 and SSN 123-45-6789.", [], set())
    assert v["verdict"] == "blocked"
    assert "180" not in v["rendered_answer"] and "123-45-6789" not in v["rendered_answer"]
    assert "verify" in v["rendered_answer"].lower()


def test_v1_v2_unchanged_when_nothing_blocks_and_no_retrieved_data():
    # retrieved_data defaults to None -> T23 V1/V2 behaviour is preserved.
    v = VerificationGate().verify(
        "On Warfarin 5 mg [S1] and Metformin 500 mg [S2].",
        [{"n": 1, "ref": "prescription:1"}, {"n": 2, "ref": "prescription:999"}],
        {"prescription:1"},
    )
    assert v["verdict"] == "pass_with_flags"
    assert "[S2]" not in v["rendered_answer"] and "[S1]" in v["rendered_answer"]


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


def test_agent_passes_retrieved_data_and_blocks_a_misattributed_med():
    block = "```citations\n" + json.dumps([{"n": 1, "ref": "prescription:1"}]) + "\n```"
    final = "The patient is on Aspirin [S1].\n" + block

    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text(final)], "end_turn"),
    ])
    # the record for prescription:1 is actually Warfarin, not Aspirin
    med = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[med])

    answer = agent.run("what meds is the patient on?", pid=42)

    assert "Aspirin" not in answer            # unverified draft not shown
    assert "verify" in answer.lower()          # safe fallback
