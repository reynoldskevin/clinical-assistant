"""T79 acceptance tests (LOCKED) — V8: reject unsafe action suggestions.

Completes the "critic that rejects uncited claims OR unsafe action suggestions"
stretch goal. V8 is a BLOCKING check: a draft that makes a prescriptive clinical
directive (the read-only Co-Pilot must never recommend/prescribe/order actions)
is blocked and replaced with a tailored safe fallback. Descriptive/historical
chart facts and proper refusals are NOT blocked.

Deterministic; stdlib only, no anthropic SDK, no live API call. The implementer
writes production code in sidecar/verification.py (+ a read-only clause in
agent._SYSTEM_PROMPT) to satisfy these; tests must NOT be edited by the implementer.
"""
import json
import re
from types import SimpleNamespace

from agent import ClaudeAgent, _SYSTEM_PROMPT
from verification import VerificationGate


# --- V8: unsafe action suggestions are BLOCKED --------------------------------

# (draft, a token from the directive that must NOT survive into the fallback)
_UNSAFE_DIRECTIVES = [
    ("Administer 10 units of insulin now.", "insulin"),
    ("Discontinue the lisinopril and switch to losartan.", "lisinopril"),
    ("You should start the patient on warfarin 5 mg daily.", "warfarin"),
    ("I recommend increasing the metformin dose to 1000 mg.", "metformin"),
    ("Consider prescribing a statin for this patient.", "statin"),
]


def test_v8_blocks_each_unsafe_action_suggestion():
    for draft, leaked in _UNSAFE_DIRECTIVES:
        v = VerificationGate().verify(draft, [], set())
        assert v["verdict"] == "blocked", f"should block: {draft!r}"
        assert any(
            f["code"] == "unsafe_action_suggestion" and f.get("action") == "blocked"
            for f in v["flags"]
        ), f"missing unsafe_action_suggestion flag: {draft!r}"
        rendered = v["rendered_answer"]
        # the directive content is never shown to the clinician
        assert leaked.lower() not in rendered.lower(), f"directive leaked: {draft!r}"
        # the fallback declines to make clinical recommendations
        assert re.search(
            r"recommend|clinical action|read-only|read only", rendered.lower()
        ), f"fallback should decline to recommend: {rendered!r}"


# --- V8: descriptive facts and refusals are NOT blocked -----------------------

_SAFE_DRAFTS = [
    "The patient is currently on warfarin 5 mg daily [S1].",   # descriptive state
    "Warfarin was discontinued in 2020 [S1].",                 # historical/passive fact
    "The most recent HbA1c was 7.8% [S1].",                    # numeric result
    "I can't help with that.",                                 # plain refusal
    # negated non-recommendation must not trip the recommend/prescribe detector
    "I don't make treatment recommendations; the clinician decides on any changes.",
]


def test_v8_does_not_block_descriptive_facts_or_refusals():
    for draft in _SAFE_DRAFTS:
        v = VerificationGate().verify(draft, [], set())
        assert not any(
            f["code"] == "unsafe_action_suggestion" for f in v["flags"]
        ), f"false positive unsafe_action flag on: {draft!r}"


def test_v8_does_not_block_reported_or_third_party_recommendations():
    # The Co-Pilot REPORTING what a guideline / note / provider recommended is a
    # legitimate cited factual/evidence answer (cf. the T50 guideline-evidence
    # split) — NOT the assistant issuing a directive. Only first-person /
    # imperative "assistant-voice" directives are unsafe; reported ones are facts.
    reported = [
        "Guidelines recommend increasing the dose when INR is subtherapeutic [S1].",
        "The ADA guidelines recommend starting metformin as first-line therapy [S1].",
        "Per the note, the provider recommended starting insulin [S1].",
        "The cardiologist recommended discontinuing the beta-blocker [S1].",
        "The discharge summary advised starting a statin [S1].",
    ]
    for draft in reported:
        v = VerificationGate().verify(draft, [], set())
        assert not any(
            f["code"] == "unsafe_action_suggestion" for f in v["flags"]
        ), f"over-blocked a reported/third-party recommendation: {draft!r}"


def test_v8_does_not_block_documented_historical_actions():
    # Documented history of an action (past tense / passive / mid-sentence) is a
    # chart fact, not a directive.
    historical = [
        "The patient was started on warfarin in 2019 [S1].",
        "Metformin was increased to 1000 mg last year [S1].",
        "The patient is scheduled to start dialysis [S1].",
        "No new medications were ordered [S1].",
        "The plan documented in the note was to start insulin [S1].",
    ]
    for draft in historical:
        v = VerificationGate().verify(draft, [], set())
        assert not any(
            f["code"] == "unsafe_action_suggestion" for f in v["flags"]
        ), f"over-blocked a documented historical action: {draft!r}"


def test_v8_imperative_directive_vs_historical_passive_are_discriminated():
    # The discriminating pair: imperative "Discontinue ..." blocks; the passive
    # historical "was discontinued ..." does not.
    imperative = VerificationGate().verify("Discontinue the warfarin today.", [], set())
    historical = VerificationGate().verify("Warfarin was discontinued in 2020 [S1].", [], set())
    assert imperative["verdict"] == "blocked"
    assert historical["verdict"] != "blocked"


# --- AC4: existing blocking checks + fallbacks are unchanged -------------------

def test_existing_v6_fallback_still_mentions_verify_not_the_action_fallback():
    # A V6 (identifier-leak) block keeps its own "verify" fallback — the V8 action
    # fallback only replaces drafts flagged unsafe_action_suggestion.
    v = VerificationGate().verify("The patient's SSN is 123-45-6789.", [], set())
    assert v["verdict"] == "blocked"
    assert any(f["code"] == "out_of_scope_phi" for f in v["flags"])
    assert "verify" in v["rendered_answer"].lower()


def test_clean_descriptive_answer_still_passes_clean():
    v = VerificationGate().verify("The patient is stable.", [], set())
    assert v["verdict"] == "pass"
    assert v["flags"] == []


# --- AC5: system prompt gains a read-only / advisory stance --------------------

def test_system_prompt_states_a_read_only_advisory_stance():
    low = _SYSTEM_PROMPT.lower()
    assert "read-only" in low or "read only" in low or "advisory" in low
    # it explicitly tells the model not to recommend/prescribe/order actions
    assert re.search(
        r"(do not|don't|never|not)\b[^.]{0,60}(recommend|prescrib|order|administer|treatment)",
        low,
    ), "system prompt must forbid making clinical action recommendations"


# --- AC6: agent integration — a directive final answer is blocked --------------

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


def test_agent_blocks_a_directive_final_answer():
    # The model emits an unsafe action suggestion as its final answer.
    final = "You should start the patient on warfarin 5 mg daily."
    creator = ScriptedCreator([_resp([_text(final)], "end_turn")])
    agent = ClaudeAgent(creator, RecordingBoundary({}))

    answer = agent.run("what should we do next?", pid=42)

    assert "warfarin" not in answer.lower()   # the directive is not shown
    assert re.search(r"recommend|clinical action|read-only|read only", answer.lower())
