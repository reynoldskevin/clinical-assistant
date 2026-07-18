"""T80 acceptance tests (LOCKED) — offline real-agent regression canary + CI.

The blocking offline gate (``eval:offline`` = this test dir) catches deterministic
regressions, but a regression that UNWIRES a gate at the agent level (e.g. deleting
the ``_gate_final_answer`` call in agent.py) leaves the gate CLASSES' own unit tests
green. This canary drives the REAL ``ClaudeAgent`` end-to-end with a scripted model
and a fake boundary — no anthropic SDK, no key, deterministic — and asserts the
safety/grounding gates are actually APPLIED to the agent's answer, so unwiring any
of them fails CI. It also pins that ``eval:live`` blocks when an API key is present.
"""
import os
import re
from types import SimpleNamespace

import yaml

from agent import ClaudeAgent

GITLAB_CI = os.path.join(os.path.dirname(__file__), "..", "..", ".gitlab-ci.yml")


# --- scripted-model + boundary fakes (mirror test_verification_constraints) ----

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ScriptedCreator:
    def __init__(self, responses):
        self._responses = list(responses)

    def __call__(self, **kwargs):
        return self._responses.pop(0)


class RecordingBoundary:
    def __init__(self, summary):
        self.summary = summary

    def __call__(self, pid):
        return self.summary


def _med_tool():
    return {
        "name": "get_medications",
        "description": "get_medications tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}],
    }


def _citations(pairs):
    import json
    return "\n```citations\n" + json.dumps(pairs) + "\n```"


# --- AC1: the agent applies each gate to its own final answer ------------------

def test_canary_agent_strips_a_fabricated_citation():
    # The model cites a ref that was never retrieved this turn -> V1 must strip
    # the marker at the agent level. If _gate_final_answer is unwired, it survives.
    final = "The patient is on Warfarin [S1]." + _citations([{"n": 1, "ref": "prescription:99"}])
    agent = ClaudeAgent(ScriptedCreator([_resp([_text(final)], "end_turn")]), RecordingBoundary({}))
    answer = agent.run("what meds is the patient on?", pid=42)
    assert "[S1]" not in answer  # fabricated marker stripped


def test_canary_agent_blocks_an_identifier_leak():
    # V6 at the agent level (the cited display path, where the full verification
    # gate runs): a raw SSN in the draft is blocked + safe fallback shown.
    final = "The patient's SSN is 123-45-6789 [S1]." + _citations([{"n": 1, "ref": "prescription:1"}])
    agent = ClaudeAgent(
        ScriptedCreator([
            _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
            _resp([_text(final)], "end_turn"),
        ]),
        RecordingBoundary({}),
        extra_tools=[_med_tool()],
    )
    answer = agent.run("what is the SSN?", pid=42)
    assert "123-45-6789" not in answer
    assert "verify" in answer.lower()


def test_canary_agent_blocks_an_unsafe_directive_on_the_cited_path():
    # V8 must fire even when the directive carries a (valid) citation block.
    final = "You should start warfarin 5 mg daily [S1]." + _citations([{"n": 1, "ref": "prescription:1"}])
    agent = ClaudeAgent(
        ScriptedCreator([
            _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
            _resp([_text(final)], "end_turn"),
        ]),
        RecordingBoundary({}),
        extra_tools=[_med_tool()],
    )
    answer = agent.run("what should we do next?", pid=42)
    assert "warfarin" not in answer.lower()  # directive content not shown
    assert re.search(r"recommend|read-only|read only|clinical action", answer.lower())


def test_canary_healthy_grounded_answer_is_not_over_blocked():
    # A properly grounded, cited, non-directive answer must pass through intact —
    # the gates must not over-block a good answer.
    final = "Warfarin is active [S1]." + _citations([{"n": 1, "ref": "prescription:1"}])
    agent = ClaudeAgent(
        ScriptedCreator([
            _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
            _resp([_text(final)], "end_turn"),
        ]),
        RecordingBoundary({}),
        extra_tools=[_med_tool()],
    )
    answer = agent.run("is warfarin active?", pid=42)
    assert "Warfarin" in answer
    assert "[S1]" in answer            # citation preserved (not stripped/blocked)
    assert "verify" not in answer.lower()  # not the blocked fallback


# --- AC3: eval:live blocks when an API key is configured -----------------------

def test_live_eval_is_blocking_when_the_api_key_is_present():
    with open(GITLAB_CI) as fh:
        data = yaml.safe_load(fh)
    live = data["eval:live"]
    rules = live["rules"]

    # A rule runs the scored sweep automatically AND blocking when the key is set.
    key_rules = [r for r in rules if "$ANTHROPIC_API_KEY" in str(r.get("if", ""))]
    assert key_rules, "eval:live must have an $ANTHROPIC_API_KEY rule"
    assert all(r.get("allow_failure") is False for r in key_rules), \
        "the keyed rule must block (allow_failure: false)"

    # Keyless: a manual, non-blocking fallback remains so keyless CI is unaffected.
    assert any(r.get("when") == "manual" and r.get("allow_failure") is True for r in rules)

    # The scored command (exit 1 on regression) is unchanged.
    script = " ".join(live["script"])
    assert "python -m eval --live --threshold 0.9" in script
