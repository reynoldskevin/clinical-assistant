"""Deterministic grounding gate for draft answers (ARCHITECTURE.md §4–§5).

Two checks run on a draft answer that used the §4 grounding format before it
reaches the clinician:

* **V1 (citation validity):** every ``[Sn]`` marker must resolve to a citation
  whose ``ref`` was actually retrieved this turn (or is the sentinel
  ``openemr:_absence`` for verified negatives). A citation pointing at a ref the
  tools never returned is *fabricated*: its markers are stripped from the
  rendered text, its citation is dropped, and a ``fabricated_citation`` flag is
  raised.
* **V2 (claim grounding):** a sentence that is a *numeric clinical assertion*
  (crude, documented heuristic: it contains a digit) must carry at least one
  valid ``[Sn]`` marker. If not, the sentence is *demoted* by appending
  " (not supported by the record)" and an ``ungrounded_claim`` flag is raised.

The gate is pure and deterministic — stdlib only, no network, no I/O. V1/V2
never *block*; the verdict is ``pass`` when there are no flags and
``pass_with_flags`` otherwise.

Two additional constraints (T24) *do* block. A blocking flag forces the verdict
to ``blocked`` and replaces the draft with a safe fallback — the unverified draft
is never shown:

* **V3 (contradiction, BLOCKING):** a citation to a medication/allergy record
  (a ``prescription:`` or ``list:`` ref) whose record is known this turn must
  name that record. If the sentence carrying the ``[Sn]`` marker does not mention
  the record's drug/title name (case-insensitive, first-token match), the med is
  misattributed/fabricated — a ``contradicts_record`` flag is raised and the
  answer is blocked.
* **V6 (patient scope, BLOCKING):** the answer must not leak raw identifiers. An
  SSN pattern or an ``MRN``/``medical record number`` label followed by digits
  raises an ``out_of_scope_phi`` flag and blocks.
* **V7 (status/negation contradiction, BLOCKING):** a citation to a
  medication/allergy record (a ``prescription:`` or ``list:`` ref) whose record
  is known this turn and is currently ``active`` (and *not* the ambiguous
  ``status_conflict`` stale-active case) must not be described as
  inactive/resolved/negated. If the sentence carrying the ``[Sn]`` marker
  contains an inactive/negated status phrase (e.g. "resolved", "discontinued",
  "no longer"), the assertion contradicts the chart — a ``contradicts_status``
  flag is raised and the answer is blocked. When the record is inactive, or the
  stale-active ``status_conflict`` flag is set, the statement is defensible and
  V7 does not fire.

**Deferred (NOT implemented — require clinical sign-off):** V4 (physiologic-range
checks) and V5 (order/dose classifier). They need validated ranges / a validated
classifier, so they are documented here rather than guessed at. No stub logic.

Documented limits (§5.3): the V2 digit heuristic misses non-numeric assertions
(medication/problem statements without a number); those are V3's concern. The
gate is only as strong as its constraint set.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# The sentinel ref for a verified negative ("not documented in the record").
_ABSENCE_REF = "openemr:_absence"

# Matches an inline citation marker like ``[S1]`` and captures its number.
_MARKER_RE = re.compile(r"\[S(\d+)\]")

# Splits text into sentences: everything up to and including a run of
# sentence-ending punctuation. The trailing group keeps any final fragment
# without terminal punctuation.
_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]+|[^.!?]+$")

# A ``.`` flanked by digits is a decimal point (e.g. ``2.5``), not a sentence
# terminator. Splitting on it would corrupt clinical values (INR, HbA1c, doses).
# We swap such dots for a placeholder before splitting and restore them after,
# so the surrounding text is preserved byte-for-byte.
_DECIMAL_DOT_RE = re.compile(r"(?<=\d)\.(?=\d)")
_DECIMAL_DOT_PLACEHOLDER = "\x00"

# Ref prefixes that denote a medication or allergy record — the only refs V3
# (contradiction) applies to.
_MED_ALLERGY_PREFIXES = ("prescription:", "list:")

# V7 inactive/negated status phrases. A record the chart marks currently active
# must not be described with any of these. Kept deliberately tight — whole-word
# where a bare stem could false-positive (``stopped`` inside ``unstopped`` etc.)
# — and pointedly excludes positive/current phrasing like "actively on".
_INACTIVE_STATUS_RE = re.compile(
    r"\b(?:resolved|inactive|discontinued|no longer|no history of|"
    r"not taking|not currently|not active|stopped taking|stopped)\b",
    re.IGNORECASE,
)

# V6 identifier patterns. An SSN (###-##-####) or an MRN / "medical record
# number" label followed by punctuation/whitespace then digits.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# ``\bMRN`` (no trailing ``\b``) so a glued ``MRN12345`` — an MRN label directly
# followed by digits — is caught too, not only separated forms like ``MRN 12345``.
_MRN_RE = re.compile(
    r"(?:\bMRN|medical record number)[\s:#.\-]*\d",
    re.IGNORECASE,
)

# Shown in place of a blocked draft. Must contain "verify" (asserted by tests)
# and none of the unverified draft's content.
_SAFE_FALLBACK = "I can't verify that against the record."


class VerificationGate:
    """Runs the deterministic V1/V2 grounding checks on a draft answer."""

    def verify(
        self,
        draft: str,
        citations: list[dict[str, Any]],
        retrieved_refs: Iterable[str],
        retrieved_data: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Verify ``draft`` against its ``citations`` and the retrieved records.

        Args:
            draft: The rendered answer text, carrying inline ``[Sn]`` markers.
            citations: A list of ``{"n": int, "ref": str}`` mapping each marker
                number to the ref it claims to cite.
            retrieved_refs: The set of refs the tools returned this turn.
            retrieved_data: Optional map of ``ref -> record`` (the tool row, e.g.
                ``{"drug": "Warfarin"}``) for the refs seen this turn. Enables the
                blocking V3 contradiction check. ``None`` preserves exact T23
                (V1/V2-only) behaviour.

        Returns:
            ``{"verdict": str, "flags": list[dict], "rendered_answer": str}``
            per §5.2. ``verdict`` is ``"blocked"`` when any blocking (V3/V6) flag
            is raised — blocking takes precedence over ``pass_with_flags`` — else
            ``"pass"`` when ``flags`` is empty, else ``"pass_with_flags"``.
        """
        # --- V3 + V6: blocking constraints (evaluated on the original draft) --
        # A block short-circuits: the unverified draft is replaced wholesale by
        # the safe fallback, so V1/V2 transforms are irrelevant on this path.
        blocking_flags: list[dict[str, Any]] = []
        blocking_flags += self._check_contradiction(draft, citations, retrieved_data)
        blocking_flags += self._check_identifier_leak(draft)
        blocking_flags += self._check_status_contradiction(
            draft, citations, retrieved_data
        )
        if blocking_flags:
            return {
                "verdict": "blocked",
                "flags": blocking_flags,
                "rendered_answer": _SAFE_FALLBACK,
            }

        # V4 (physiologic-range) and V5 (order/dose classifier) are DEFERRED —
        # they require clinical sign-off (validated ranges / classifier) and are
        # intentionally not implemented here.

        valid_refs = set(retrieved_refs) | {_ABSENCE_REF}

        flags: list[dict[str, Any]] = []
        rendered = draft
        valid_numbers: set[int] = set()

        # --- V1: citation validity -------------------------------------------
        for citation in citations:
            ref = citation["ref"]
            n = citation["n"]
            if ref in valid_refs:
                valid_numbers.add(n)
                continue
            # Fabricated: strip its marker (drop a leading space with it so no
            # double-spaces remain) and drop the citation.
            flags.append(
                {"code": "fabricated_citation", "ref": ref, "action": "stripped"}
            )
            rendered = rendered.replace(f" [S{n}]", "").replace(f"[S{n}]", "")

        # --- V2: claim grounding ---------------------------------------------
        rendered = self._demote_ungrounded(rendered, valid_numbers, flags)

        verdict = "pass" if not flags else "pass_with_flags"
        return {"verdict": verdict, "flags": flags, "rendered_answer": rendered}

    @staticmethod
    def _check_contradiction(
        draft: str,
        citations: list[dict[str, Any]],
        retrieved_data: dict[str, dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """V3 (BLOCKING): a cited med/allergy must actually be that record.

        For each citation to a ``prescription:``/``list:`` ref whose record is
        known, the record's drug/title first token must appear (case-insensitive)
        in the sentence carrying that ``[Sn]`` marker. If it does not, the med is
        misattributed and a blocking ``contradicts_record`` flag is raised.
        """
        data = retrieved_data or {}
        flags: list[dict[str, Any]] = []
        for citation in citations:
            ref = citation["ref"]
            if not ref.startswith(_MED_ALLERGY_PREFIXES):
                continue
            record = data.get(ref)
            if record is None:
                continue
            name = record.get("drug") or record.get("title")
            if not name:
                continue
            sentence = VerificationGate._sentence_with_marker(draft, citation["n"])
            if sentence is None:
                continue
            first_token = name.split()[0].lower()
            if first_token not in sentence.lower():
                flags.append(
                    {"code": "contradicts_record", "ref": ref, "action": "blocked"}
                )
        return flags

    @staticmethod
    def _check_status_contradiction(
        draft: str,
        citations: list[dict[str, Any]],
        retrieved_data: dict[str, dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """V7 (BLOCKING): don't call a currently-active record inactive/resolved.

        For each citation to a ``prescription:``/``list:`` ref whose record is
        known and currently ``active`` — excluding the ambiguous stale-active
        ``status_conflict`` case, where hedging toward "resolved" is defensible —
        the sentence carrying that ``[Sn]`` marker must not contain an
        inactive/negated status phrase. If it does, the assertion contradicts the
        chart and a blocking ``contradicts_status`` flag is raised.
        """
        data = retrieved_data or {}
        flags: list[dict[str, Any]] = []
        for citation in citations:
            ref = citation["ref"]
            if not ref.startswith(_MED_ALLERGY_PREFIXES):
                continue
            record = data.get(ref)
            if record is None:
                continue
            # Only fire for genuinely-active records that are not the ambiguous
            # stale-active (end_date present) case.
            if record.get("active") is not True or record.get("status_conflict"):
                continue
            sentence = VerificationGate._sentence_with_marker(draft, citation["n"])
            if sentence is None:
                continue
            if _INACTIVE_STATUS_RE.search(sentence):
                flags.append(
                    {"code": "contradicts_status", "ref": ref, "action": "blocked"}
                )
        return flags

    @staticmethod
    def _sentence_with_marker(draft: str, n: int) -> str | None:
        """Return the sentence in ``draft`` that carries the ``[Sn]`` marker."""
        marker = f"[S{n}]"
        protected = _DECIMAL_DOT_RE.sub(_DECIMAL_DOT_PLACEHOLDER, draft)
        for match in _SENTENCE_RE.finditer(protected):
            sentence = match.group(0).replace(_DECIMAL_DOT_PLACEHOLDER, ".")
            if marker in sentence:
                return sentence
        return None

    @staticmethod
    def _check_identifier_leak(draft: str) -> list[dict[str, Any]]:
        """V6 (BLOCKING): block a raw SSN or MRN/medical-record-number leak."""
        if _SSN_RE.search(draft) or _MRN_RE.search(draft):
            return [{"code": "out_of_scope_phi", "action": "blocked"}]
        return []

    def _demote_ungrounded(
        self,
        text: str,
        valid_numbers: set[int],
        flags: list[dict[str, Any]],
    ) -> str:
        """Demote numeric assertion sentences lacking a valid ``[Sn]`` marker."""
        # Protect decimal points from the splitter so ``2.5`` is not cut into a
        # bogus ``2.`` sentence, then restore them on every emitted fragment.
        protected = _DECIMAL_DOT_RE.sub(_DECIMAL_DOT_PLACEHOLDER, text)

        pieces: list[str] = []
        for match in _SENTENCE_RE.finditer(protected):
            sentence = match.group(0).replace(_DECIMAL_DOT_PLACEHOLDER, ".")
            if self._is_grounded_or_not_numeric(sentence, valid_numbers):
                pieces.append(sentence)
                continue
            flags.append(
                {"code": "ungrounded_claim", "span": sentence, "action": "demoted"}
            )
            pieces.append(self._append_demotion(sentence))
        return "".join(pieces)

    @staticmethod
    def _is_grounded_or_not_numeric(sentence: str, valid_numbers: set[int]) -> bool:
        """True if the sentence is a non-assertion or already grounded."""
        if not re.search(r"\d", sentence):
            return True
        return any(
            int(m.group(1)) in valid_numbers for m in _MARKER_RE.finditer(sentence)
        )

    @staticmethod
    def _append_demotion(sentence: str) -> str:
        """Append the demotion note *before* any trailing terminal punctuation."""
        note = " (not supported by the record)"
        stripped = sentence.rstrip()
        trailing = sentence[len(stripped):]
        match = re.search(r"[.!?]+$", stripped)
        if match:
            core = stripped[: match.start()]
            punct = stripped[match.start():]
            return core + note + punct + trailing
        return stripped + note + trailing
