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
* **V8 (unsafe action suggestion, BLOCKING):** the Co-Pilot is read-only and
  advisory — it surfaces chart facts and never issues a prescriptive clinical
  directive. A draft that recommends/prescribes/orders a clinical action raises
  an ``unsafe_action_suggestion`` flag and is blocked, replaced with a tailored
  ``_ACTION_FALLBACK`` that declines to make recommendations (distinct from the
  generic "verify" fallback used by V3/V6/V7). The detector is a documented
  heuristic operating sentence-by-sentence: it matches (a) a recommendation
  lead-in (``recommend``/``advise``/``suggest``/``consider``) or ``should``
  immediately followed by a prescriptive action verb, but NOT when negated by a
  preceding ``don't``/``can't``/``never``/``no`` in the clause; and (b) a
  sentence-initial imperative base-form action verb (``Start``, ``Administer``,
  ``Discontinue``, ``Switch``, ...). Base form only, so past-tense/passive
  phrasing ("was discontinued", "Increased risk") is descriptive and does not
  fire.

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

# Shown in place of a draft blocked by V8 (an unsafe action suggestion). Unlike
# _SAFE_FALLBACK it declines to make a clinical recommendation rather than citing
# an inability to verify — the read-only stance, not a grounding failure.
_ACTION_FALLBACK = (
    "I can't provide clinical recommendations — I'm a read-only assistant that "
    "surfaces chart facts for the clinician to decide."
)

# V8 prescriptive action verbs. Stems (matched with a trailing ``\w*``) so a verb
# and its inflections are covered, but *only* the base/imperative form is used by
# the imperative check below; past-tense/passive detection is handled separately.
_ACTION_VERB_STEMS = (
    r"start|increas|decreas|add|prescrib|administ|order|discontinu|switch|"
    r"taper|titrat|initiat|begin|give|hold|stop"
)

# V8 (a): a recommendation lead-in (recommend/advise/suggest/consider) or
# ``should``, immediately followed by a prescriptive action verb. The action verb
# may be an ``-ing`` gerund ("increasing the dose") or a base form
# ("prescribe a statin"), so the verb stem alone is enough after the lead-in.
_RECOMMEND_ACTION_RE = re.compile(
    r"\b(?:recommend|advise|suggest|consider|should)\w*\s+"
    r"(?:the\s+patient\s+(?:on|start)\s+|(?:start\w*\s+the\s+patient\s+on\s+)|"
    rf"(?:{_ACTION_VERB_STEMS})\w*)",
    re.IGNORECASE,
)

# V8 negation guard: a negation token appearing before the recommendation
# lead-in in the same sentence makes it a *refusal to recommend*, not a
# recommendation ("I don't make treatment recommendations").
_NEGATION_RE = re.compile(
    r"\b(?:don't|do not|doesn't|does not|can't|cannot|won't|will not|"
    r"never|no|not)\b",
    re.IGNORECASE,
)

# V8 own-voice guard: the recommend-branch must fire ONLY on the assistant's
# *own-voice* directive, not on a report of what a third party recommended.
# The discriminator is the subject/voice preceding the lead-in, not tense:
#   * fires: sentence-initial imperative ("Consider prescribing…"), or a
#     first/second-person pronoun subject immediately before the lead-in
#     ("I recommend…", "we advise…", "you should start…").
#   * does NOT fire: a third-party noun-phrase subject or reporting frame
#     precedes the lead-in ("Guidelines recommend…", "The provider
#     recommended…", "The discharge summary advised…", "Per the note, …").
# ``_OWN_VOICE_LEADIN_RE`` matches the text immediately before the lead-in
# (whitespace-trimmed): empty (sentence-initial) or exactly a permitted
# pronoun subject.
_OWN_VOICE_LEADIN_RE = re.compile(
    r"^(?:i|we|you)?$",
    re.IGNORECASE,
)

# V8 (b): a sentence-initial imperative — a base-form action verb at the very
# start of the sentence (optionally after whitespace). Anchored to the base form
# with a word boundary *after* the stem-completing letters so "Discontinue" fires
# but "Discontinued" / "Increased" (past tense) does not.
_IMPERATIVE_ACTION_RE = re.compile(
    r"^\s*(?:start|administer|prescribe|order|give|increase|decrease|"
    r"discontinue|stop|hold|switch|taper|titrate|initiate|begin|add)\b",
    re.IGNORECASE,
)


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
        blocking_flags += self._check_unsafe_action(draft)
        if blocking_flags:
            # An unsafe-action block gets the tailored read-only fallback; every
            # other blocking check keeps the generic "verify" fallback.
            is_unsafe_action = any(
                f["code"] == "unsafe_action_suggestion" for f in blocking_flags
            )
            fallback = _ACTION_FALLBACK if is_unsafe_action else _SAFE_FALLBACK
            return {
                "verdict": "blocked",
                "flags": blocking_flags,
                "rendered_answer": fallback,
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

    @staticmethod
    def _check_unsafe_action(draft: str) -> list[dict[str, Any]]:
        """V8 (BLOCKING): block a prescriptive clinical directive/recommendation.

        A documented heuristic operating sentence-by-sentence (reusing the
        module's sentence splitter). A sentence trips V8 when it is either:

        * a **recommendation** in the assistant's *own voice* —
          ``recommend``/``advise``/``suggest``/``consider``/``should``
          immediately followed by a prescriptive action verb — where the
          lead-in is sentence-initial ("Consider prescribing…") or directly
          preceded by a first/second-person pronoun subject ("I recommend…",
          "we advise…", "you should start…"). It does NOT fire when a
          third-party subject or reporting frame precedes the lead-in
          ("Guidelines recommend…", "The provider recommended…", "Per the
          note, …") — that is a cited factual report, not a directive. It is
          also NOT fired when negated by a preceding ``don't``/``can't``/
          ``never``/``no`` in the same sentence (so "I don't make treatment
          recommendations" is a refusal, not a recommendation); or
        * an **imperative** — a sentence-initial base-form action verb
          (``Start``, ``Administer``, ``Discontinue``, ``Switch``, ...).

        Base form only: past-tense/passive phrasing ("was discontinued in 2020",
        "Increased risk of bleeding") is descriptive/historical and does not fire.
        Returns a single ``unsafe_action_suggestion`` flag on the first hit.
        """
        protected = _DECIMAL_DOT_RE.sub(_DECIMAL_DOT_PLACEHOLDER, draft)
        for match in _SENTENCE_RE.finditer(protected):
            sentence = match.group(0).replace(_DECIMAL_DOT_PLACEHOLDER, ".")
            # (a) recommendation lead-in + action verb, unless negated earlier.
            rec = _RECOMMEND_ACTION_RE.search(sentence)
            if rec is not None:
                preceding = sentence[: rec.start()]
                # Own-voice guard: the text between the start of the clause and
                # the lead-in must be empty (sentence-initial imperative) or a
                # bare first/second-person pronoun subject. A third-party noun
                # subject ("Guidelines", "the provider", "The discharge
                # summary") or a reporting frame ("Per the note, ") means the
                # draft is reporting someone else's recommendation, not issuing
                # one — do not fire.
                lead_in_context = preceding.strip().rstrip(",")
                own_voice = _OWN_VOICE_LEADIN_RE.match(lead_in_context) is not None
                if own_voice and _NEGATION_RE.search(preceding) is None:
                    return [
                        {"code": "unsafe_action_suggestion", "action": "blocked"}
                    ]
            # (b) sentence-initial imperative base-form action verb.
            if _IMPERATIVE_ACTION_RE.search(sentence.lstrip()):
                return [{"code": "unsafe_action_suggestion", "action": "blocked"}]
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
