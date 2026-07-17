"""Deterministic PHI-shape detector for the Week-2 log/trace emission guard.

Pure stdlib (``re`` only): no dependencies, no network, no ``yaml`` import.

Two entry points:

* :func:`find_phi` — flags every PHI-shaped substring (``ssn`` / ``mrn`` /
  ``dob`` / ``phone`` / ``lab_value``).
* :func:`find_identifiers` — flags ONLY the direct patient identifiers
  (``ssn`` / ``mrn`` / ``dob`` / ``phone``). Clinical value shapes
  (``lab_value``) are deliberately excluded: public guideline text legitimately
  rides along in a trace's retrieval hits and carries value shapes like
  "< 7 %", which are not patient identifiers.

Patterns are intentionally precise so that the serialized per-turn trace — which
contains integer token counts, a ``cost_usd`` float, and guideline snippets — does
not trip the identifier guard.
"""
from __future__ import annotations

import re

# --- direct patient identifiers ---------------------------------------------
# SSN: NNN-NN-NNNN (2-digit middle group distinguishes it from a phone).
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Phone: NNN-NNN-NNNN (3-digit middle group) or (NNN) NNN-NNNN.
_PHONE = re.compile(r"\b\d{3}-\d{3}-\d{4}\b|\(\d{3}\)\s*\d{3}-\d{4}")
# DOB: ISO date or M/D/YYYY.
_DOB = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b")
# MRN: LABELED only — a bare digit run must not trip (token counts, ports, scores).
_MRN = re.compile(r"(?i)\bMRN\b[:#\s]*\d+")

# --- clinical value shape (NOT an identifier) -------------------------------
_LAB_VALUE = re.compile(
    r"(?i)\b\d+(?:\.\d+)?\s?(?:mg/dL|mmol/L|mEq/L|g/dL|IU/L|ng/mL|mcg|mg|%)\b"
)

_IDENTIFIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ssn", _SSN),
    ("phone", _PHONE),
    ("dob", _DOB),
    ("mrn", _MRN),
)

_ALL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = _IDENTIFIER_PATTERNS + (
    ("lab_value", _LAB_VALUE),
)


def _scan(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> list[dict]:
    found: list[dict] = []
    for kind, pattern in patterns:
        for m in pattern.finditer(text):
            found.append({"kind": kind, "match": m.group(0)})
    return found


def find_phi(text: str) -> list[dict]:
    """Return every PHI-shaped substring found in ``text`` (all kinds)."""
    return _scan(text, _ALL_PATTERNS)


def find_identifiers(text: str) -> list[dict]:
    """Return only DIRECT patient-identifier shapes (excludes ``lab_value``)."""
    return _scan(text, _IDENTIFIER_PATTERNS)
