"""T68 acceptance tests (LOCKED) — deterministic wrong-chart identity check.

The wrong-chart / wrong-patient safety check moves EARLIER in the lifecycle:
upload → extract → check-file-matches-patient → warn. This module is the pure,
offline core: it compares the strong identifiers parsed out of a VLM-normalized
intake `demographics` string (DOB, sex, name) against the chart's structured
demographics dict (`fname`, `lname`, `dob`, `sex`, …), and reports whether they
match — with NO LLM call.

It is CONSERVATIVE: an identifier is only "checked" when confidently present on
BOTH sides, and a mismatch is only raised on a clear conflict of a checked
identifier. An absent/unparseable identifier is never a mismatch (no false
alarms). Everything here is deterministic — no network, no I/O, no randomness.

Contract exercised (the implementer builds `sidecar/identity_check.py`):

    IdentityCheck                      # frozen: matches, mismatched_identifiers, checked_identifiers
    check_identity(intake_demographics: str | None, chart_demographics: dict | None) -> IdentityCheck
"""
from identity_check import IdentityCheck, check_identity


# The seeded chart demographics (mirrors the synthetic intake fixture's chart).
CHART = {
    "pid": 1,
    "fname": "Brett333",
    "lname": "Cruickshank494",
    "dob": "1925-06-24",
    "sex": "Female",
    "race": "white",
    "ethnicity": "not_hisp_or_latin",
}


def _mismatch(intake, chart=CHART):
    return check_identity(intake, chart)


# --- exact match --------------------------------------------------------------

def test_all_identifiers_match_is_a_clean_match():
    result = _mismatch("Brett333 Cruickshank494; DOB 1925-06-24; Female")
    assert isinstance(result, IdentityCheck)
    assert result.matches is True
    assert result.mismatched_identifiers == []
    # All three strong identifiers were comparable.
    assert set(result.checked_identifiers) == {"name", "DOB", "sex"}


# --- single-identifier conflicts ---------------------------------------------

def test_dob_conflict_only():
    result = _mismatch("Brett333 Cruickshank494; DOB 1990-01-01; Female")
    assert result.matches is False
    assert result.mismatched_identifiers == ["DOB"]


def test_sex_conflict_only():
    result = _mismatch("Brett333 Cruickshank494; DOB 1925-06-24; Male")
    assert result.matches is False
    assert result.mismatched_identifiers == ["sex"]


def test_name_conflict_only():
    result = _mismatch("Jordan Rivera; DOB 1925-06-24; Female")
    assert result.matches is False
    assert result.mismatched_identifiers == ["name"]


# --- the real fixtures --------------------------------------------------------

def test_wrong_chart_fixture_mismatches_on_all_three():
    # The synthetic "wrong chart" intake (Jordan A. Rivera) vs the seeded chart.
    result = _mismatch("Jordan A. Rivera; DOB 1988-03-02; Male")
    assert result.matches is False
    # Canonical order is name, DOB, sex.
    assert result.mismatched_identifiers == ["name", "DOB", "sex"]


def test_matching_fixture_is_a_clean_match():
    result = _mismatch("Brett333 Cruickshank494; DOB 1925-06-24; Female")
    assert result.matches is True
    assert result.mismatched_identifiers == []


# --- conservative: absent / unparseable identifiers are never a mismatch ------

def test_missing_dob_in_intake_is_not_checked():
    result = _mismatch("Brett333 Cruickshank494; Female")
    assert result.matches is True
    assert "DOB" not in result.checked_identifiers
    assert "DOB" not in result.mismatched_identifiers


def test_missing_chart_dob_is_not_checked():
    chart = {**CHART, "dob": ""}
    result = check_identity("Brett333 Cruickshank494; DOB 1990-01-01; Female", chart)
    assert "DOB" not in result.checked_identifiers
    assert result.matches is True


def test_intake_without_a_name_does_not_check_or_flag_name():
    # "F, 54, DOB 1967-02-11" carries a sex + DOB but no name — name must not be
    # checked (no false name mismatch), while DOB is still compared.
    result = _mismatch("F, 54, DOB 1967-02-11")
    assert "name" not in result.checked_identifiers
    assert "name" not in result.mismatched_identifiers
    # DOB differs from the chart's 1925-06-24, so it IS flagged.
    assert "DOB" in result.mismatched_identifiers
    # Sex "F" matches the chart's "Female".
    assert "sex" not in result.mismatched_identifiers


def test_non_iso_date_is_not_parsed_so_dob_is_not_checked():
    # Only ISO YYYY-MM-DD is compared; an ambiguous 03/02/1988 is not a mismatch.
    result = _mismatch("Brett333 Cruickshank494; DOB 03/02/1988; Female")
    assert "DOB" not in result.checked_identifiers
    assert result.matches is True


# --- nothing comparable → fail-open (no warning) -----------------------------

def test_none_intake_is_a_safe_match():
    result = check_identity(None, CHART)
    assert result.matches is True
    assert result.checked_identifiers == []
    assert result.mismatched_identifiers == []


def test_none_chart_is_a_safe_match():
    result = check_identity("Brett333 Cruickshank494; DOB 1925-06-24; Female", None)
    assert result.matches is True
    assert result.checked_identifiers == []


def test_empty_chart_dict_is_a_safe_match():
    result = check_identity("Jordan Rivera; DOB 1988-03-02; Male", {})
    assert result.matches is True
    assert result.checked_identifiers == []


# --- case / format insensitivity ---------------------------------------------

def test_sex_matching_is_case_and_word_insensitive():
    assert check_identity("Brett333 Cruickshank494; DOB 1925-06-24; female", CHART).matches is True
    male_chart = {**CHART, "sex": "M"}
    assert check_identity("Brett333 Cruickshank494; DOB 1925-06-24; MALE", male_chart).matches is True


def test_surname_matches_as_a_case_insensitive_token():
    result = _mismatch("brett333 cruickshank494; DOB 1925-06-24; Female")
    assert "name" not in result.mismatched_identifiers
    assert result.matches is True


# --- invariants ---------------------------------------------------------------

def test_matches_is_exactly_the_empty_mismatch_invariant():
    for intake in (
        "Brett333 Cruickshank494; DOB 1925-06-24; Female",
        "Jordan A. Rivera; DOB 1988-03-02; Male",
        "Brett333 Cruickshank494; DOB 1990-01-01; Female",
        None,
        "",
    ):
        result = check_identity(intake, CHART)
        assert result.matches == (result.mismatched_identifiers == [])


def test_mismatched_identifiers_use_canonical_order():
    # Even if internally computed in another order, the output is name, DOB, sex.
    result = _mismatch("Jordan A. Rivera; DOB 1988-03-02; Male")
    order = {name: i for i, name in enumerate(["name", "DOB", "sex"])}
    assert result.mismatched_identifiers == sorted(
        result.mismatched_identifiers, key=lambda n: order[n]
    )


def test_is_deterministic():
    a = _mismatch("Jordan A. Rivera; DOB 1988-03-02; Male")
    b = _mismatch("Jordan A. Rivera; DOB 1988-03-02; Male")
    assert a == b
