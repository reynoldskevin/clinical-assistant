"""Deterministic, offline wrong-chart / wrong-patient identity check.

Compares the strong identifiers (name, DOB, sex) parsed out of a VLM-normalized
intake ``demographics`` string against the chart's structured demographics dict
(``fname``, ``lname``, ``dob``, ``sex``). Reports whether they match — with NO
LLM call, no network, no I/O, no randomness, no clock.

CONSERVATIVE by design: an identifier is only "checked" when it is confidently
present on BOTH sides, and a mismatch is only raised on a clear conflict of a
checked identifier. An absent or unparseable identifier is never a mismatch, so
there are no false alarms. When nothing is comparable, the result is a fail-open
clean match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical output order for both identifier lists.
_CANONICAL_ORDER = ["name", "DOB", "sex"]
_ORDER_INDEX = {name: i for i, name in enumerate(_CANONICAL_ORDER)}

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# female must be tested before male (the word "female" contains "male").
# Intake side: only the SPELLED-OUT words. A bare single-letter f/m on an
# intake form is almost always a middle initial ("John F. Kennedy"), never a
# reliable sex token, so we do not infer sex from it (no false alarms).
# Chart side: the structured `sex` column legitimately stores "M"/"F", so the
# chart-side normalizer also accepts the standalone single-letter form.
_INTAKE_FEMALE_RE = re.compile(r"\bfemale\b", re.IGNORECASE)
_INTAKE_MALE_RE = re.compile(r"\bmale\b", re.IGNORECASE)
_CHART_FEMALE_RE = re.compile(r"\b(?:female|f)\b", re.IGNORECASE)
_CHART_MALE_RE = re.compile(r"\b(?:male|m)\b", re.IGNORECASE)

# Tokens that are never name-like when scanning the intake for a name.
_SEX_STOP_TOKENS = {"male", "female", "m", "f"}
_NAME_TOKEN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class IdentityCheck:
    matches: bool
    mismatched_identifiers: list[str] = field(default_factory=list)
    checked_identifiers: list[str] = field(default_factory=list)


def _parse_intake_dob(intake: str) -> str | None:
    """First ISO YYYY-MM-DD date in the intake string, or None."""
    match = _ISO_DATE_RE.search(intake)
    return match.group(0) if match else None


def _normalize_intake_sex(value: str | None) -> str | None:
    """Normalize a SPELLED-OUT intake sex word to "F"/"M" (no single letters)."""
    if not value:
        return None
    if _INTAKE_FEMALE_RE.search(value):
        return "F"
    if _INTAKE_MALE_RE.search(value):
        return "M"
    return None


def _normalize_chart_sex(value: str | None) -> str | None:
    """Normalize a chart sex value ("Female"/"Male"/"F"/"M") to "F"/"M"."""
    if not value:
        return None
    if _CHART_FEMALE_RE.search(value):
        return "F"
    if _CHART_MALE_RE.search(value):
        return "M"
    return None


def _intake_has_name_token(intake: str) -> bool:
    """True if the intake carries at least one name-like token."""
    for raw in re.split(r"[\s,;]+", intake):
        token = raw.strip()
        if len(token) < 2:
            continue
        if not _NAME_TOKEN_RE.search(token):
            continue
        lowered = token.lower()
        if lowered in _SEX_STOP_TOKENS or lowered == "dob":
            continue
        if token.isdigit():
            continue
        return True
    return False


def check_identity(
    intake_demographics: str | None,
    chart_demographics: dict | None,
) -> IdentityCheck:
    if not intake_demographics or not chart_demographics:
        return IdentityCheck(matches=True, mismatched_identifiers=[], checked_identifiers=[])

    intake = intake_demographics
    checked: list[str] = []
    mismatched: list[str] = []

    # --- name ---------------------------------------------------------------
    chart_lname = str(chart_demographics.get("lname") or "").strip()
    chart_fname = str(chart_demographics.get("fname") or "").strip()
    if chart_lname and _intake_has_name_token(intake):
        checked.append("name")
        haystack = intake.casefold()
        surname_hit = chart_lname.casefold() in haystack
        given_hit = bool(chart_fname) and chart_fname.casefold() in haystack
        if not (surname_hit or given_hit):
            mismatched.append("name")

    # --- DOB ----------------------------------------------------------------
    intake_dob = _parse_intake_dob(intake)
    chart_dob = str(chart_demographics.get("dob") or "").strip()
    if intake_dob and chart_dob:
        checked.append("DOB")
        if intake_dob.strip() != chart_dob:
            mismatched.append("DOB")

    # --- sex ----------------------------------------------------------------
    intake_sex = _normalize_intake_sex(intake)
    chart_sex = _normalize_chart_sex(chart_demographics.get("sex"))
    if intake_sex and chart_sex:
        checked.append("sex")
        if intake_sex != chart_sex:
            mismatched.append("sex")

    checked.sort(key=lambda n: _ORDER_INDEX[n])
    mismatched.sort(key=lambda n: _ORDER_INDEX[n])

    return IdentityCheck(
        matches=(mismatched == []),
        mismatched_identifiers=mismatched,
        checked_identifiers=checked,
    )
