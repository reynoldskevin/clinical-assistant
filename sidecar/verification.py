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
never *block* (that is V5/V6, out of scope here); the verdict is ``pass`` when
there are no flags and ``pass_with_flags`` otherwise.

Documented limits (§5.3): the digit heuristic misses non-numeric assertions
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


class VerificationGate:
    """Runs the deterministic V1/V2 grounding checks on a draft answer."""

    def verify(
        self,
        draft: str,
        citations: list[dict[str, Any]],
        retrieved_refs: Iterable[str],
    ) -> dict[str, Any]:
        """Verify ``draft`` against its ``citations`` and the ``retrieved_refs``.

        Args:
            draft: The rendered answer text, carrying inline ``[Sn]`` markers.
            citations: A list of ``{"n": int, "ref": str}`` mapping each marker
                number to the ref it claims to cite.
            retrieved_refs: The set of refs the tools returned this turn.

        Returns:
            ``{"verdict": str, "flags": list[dict], "rendered_answer": str}``
            per §5.2. ``verdict`` is ``"pass"`` when ``flags`` is empty, else
            ``"pass_with_flags"``.
        """
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
