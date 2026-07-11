"""T29 acceptance tests (LOCKED) — verification gate constraint V7.

V7 (status/negation contradiction) is a BLOCKING check: an answer that asserts an
inactive/resolved status about a record the chart marks *active* (and not stale)
violates what the underlying data says, so it is blocked and replaced with the
safe fallback. The genuinely-ambiguous stale-active case (`status_conflict`) is
deliberately exempt — the agent is entitled to hedge there. Deterministic; no
anthropic SDK, no live API call.
"""
from verification import VerificationGate


# --- V7 blocks an inactive-status assertion about an active record -------------

def test_v7_resolved_assertion_about_active_record_is_blocked():
    v = VerificationGate().verify(
        "The hypertension is resolved [S1].",
        [{"n": 1, "ref": "list:1"}],
        {"list:1"},
        {"list:1": {"title": "Hypertension", "active": True, "status_conflict": False}},
    )
    assert v["verdict"] == "blocked"
    assert any(f["code"] == "contradicts_status" and f.get("ref") == "list:1" for f in v["flags"])
    # unverified draft is never shown; safe fallback is
    assert "resolved" not in v["rendered_answer"].lower()
    assert "verify" in v["rendered_answer"].lower()


def test_v7_discontinued_med_assertion_about_active_med_is_blocked():
    v = VerificationGate().verify(
        "Warfarin has been discontinued [S1].",
        [{"n": 1, "ref": "prescription:1"}],
        {"prescription:1"},
        {"prescription:1": {"drug": "Warfarin", "active": True, "status_conflict": False}},
    )
    assert v["verdict"] == "blocked"
    assert any(f["code"] == "contradicts_status" for f in v["flags"])


# --- V7 does NOT fire where the assertion is defensible -------------------------

def test_v7_exempts_stale_active_conflict_records():
    # status_conflict: active=1 but an end_date exists -> hedging "resolved" is OK.
    v = VerificationGate().verify(
        "The hypertension appears resolved [S1].",
        [{"n": 1, "ref": "list:1"}],
        {"list:1"},
        {"list:1": {"title": "Hypertension", "active": True, "status_conflict": True}},
    )
    assert v["verdict"] != "blocked"


def test_v7_accurate_resolved_assertion_about_inactive_record_passes():
    v = VerificationGate().verify(
        "The hypertension is resolved [S1].",
        [{"n": 1, "ref": "list:1"}],
        {"list:1"},
        {"list:1": {"title": "Hypertension", "active": False, "status_conflict": False}},
    )
    assert v["verdict"] != "blocked"


def test_v7_current_status_sentence_about_active_record_is_not_blocked():
    v = VerificationGate().verify(
        "The patient is actively on Warfarin [S1].",
        [{"n": 1, "ref": "prescription:1"}],
        {"prescription:1"},
        {"prescription:1": {"drug": "Warfarin", "active": True, "status_conflict": False}},
    )
    assert v["verdict"] != "blocked"


def test_v7_does_not_fire_for_non_med_allergy_refs():
    v = VerificationGate().verify(
        "The prior workup was resolved without admission [S1].",
        [{"n": 1, "ref": "pnote:1"}],
        {"pnote:1"},
        {"pnote:1": {"snippet": "workup", "active": True, "status_conflict": False}},
    )
    assert v["verdict"] != "blocked"


def test_v7_does_not_run_without_retrieved_data():
    # retrieved_data defaults to None -> T23 V1/V2 behaviour is preserved.
    v = VerificationGate().verify(
        "The hypertension is resolved [S1].",
        [{"n": 1, "ref": "list:1"}],
        {"list:1"},
    )
    assert v["verdict"] != "blocked"


# --- precedence ----------------------------------------------------------------

def test_v7_status_contradiction_takes_precedence_over_pass_with_flags():
    # An ungrounded numeric (V2 -> pass_with_flags) AND a status contradiction
    # (V7 -> block): the block wins and the draft is replaced.
    v = VerificationGate().verify(
        "Glucose was 180. The hypertension is resolved [S1].",
        [{"n": 1, "ref": "list:1"}],
        {"list:1"},
        {"list:1": {"title": "Hypertension", "active": True, "status_conflict": False}},
    )
    assert v["verdict"] == "blocked"
    assert "resolved" not in v["rendered_answer"].lower()
    assert "180" not in v["rendered_answer"]
