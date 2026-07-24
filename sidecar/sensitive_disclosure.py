"""Deterministic minimum-necessary output guardrail for the Clinical Co-Pilot.

Addresses two red-team findings — VULN-broad-query-overdisclosure (a broad "is
the patient healthy?" answered with a full dossier that volunteered a drug
overdose and rehab/detox history) and VULN-unverified-role-disclosure (a narrow
flu-shot question, prefaced by a self-asserted free-text "on-call nurse" role,
answered by volunteering the same 42 CFR Part 2 substance-use / behavioral-health
history). In both the leaked content is truthful and grounded, so the V1-V8
grounding gate passes it, and neither is a denial-of-service, so the ticket-85
request guard never fires. The failure is *over-disclosure* of a legally-protected
category the question never asked about.

This module is a deterministic OUTPUT guardrail. Unless the question explicitly
asks about the protected category, it removes answer sentences that disclose
substance-use / behavioral-health *history/events* and appends a single scoped,
PHI-free notice. It is intentionally scoped to history/events, and hardened
against false positives on legitimate clinical phrasing:

* Active medication NAMES are never redacted (a MAT drug named for a meds
  question is need-to-know for interactions), and ambiguous single words — bare
  "alcohol" (swab), bare "opioid" (analgesia), bare "rehabilitation"
  (cardiac/pulmonary) — never match on their own.
* The broad adjective "psychiatric" only matches when paired with an
  event/history word (admission, hospitalization, history, diagnosis, ...), so a
  medication sentence ("sertraline for psychiatric management, warfarin 5 mg")
  is NOT deleted wholesale — its co-located non-sensitive med survives.
* The answer-side lexicon covers common illicit-drug names and behavioral-health
  diagnoses (heroin/cocaine/methamphetamine/cannabis; bipolar/schizophrenia/
  PTSD/major depression), not only the two findings' literal vocabulary, so a
  one-word synonym swap does not defeat the guard. Ambiguous cardiology/anesthesia
  terms (bare "depression" → ST depression; "fentanyl") are deliberately excluded.
* A question that explicitly asks about the category stands the gate down — even
  when it asks for the "complete"/"full" category history — UNLESS the category
  word is merely riding inside a bulk-dump / exfiltration demand ("print the
  entire chart ... psychiatric history ... SSN"), which is the finding-2 attack,
  not a scoped clinical need-to-know.

Pure, offline, deterministic, and stdlib-only (``re`` + ``dataclasses``): no
network, no I/O, no clock, no randomness.

@package   OpenEMR
@link      https://www.open-emr.org
@license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Scoped, PHI-free notice appended when at least one protected-category sentence
# is removed. It reads as an "additional protected history is on file — ask if
# relevant" pointer: it names 42 CFR Part 2 but deliberately carries NONE of the
# category tokens (overdose/detox/rehab/substance/addiction/psychiatric), so a
# second scrub pass cannot re-match it (idempotency) and it leaks no specifics.
SENSITIVE_REDACTION_NOTICE = (
    "Additional protected history may be on file under 42 CFR Part 2; ask if it "
    "is relevant to this specific question and I can surface it."
)


@dataclass(frozen=True)
class DisclosureScrubResult:
    """Immutable result of :func:`scrub_sensitive_disclosure`.

    ``text`` is the (possibly redacted) answer; ``redacted`` is True when at
    least one protected-category sentence was removed; ``reason`` names the
    matched rule ("protected_category_minimum_necessary") or is empty.
    """

    text: str
    redacted: bool
    reason: str


_REASON = "protected_category_minimum_necessary"

# --- question side: does the question explicitly ask about the category? -----

# A protected-category ask: the question is genuinely ABOUT substance use /
# behavioral health / psychiatric care, so disclosing it is the actual need. Kept
# in sync with the answer-side lexicon so that an explicit ask about ANY covered
# category (illicit drug, mood/psychotic diagnosis) stands the gate down rather
# than being redacted back at the caller.
_PERMIT_CATEGORY_RE = re.compile(
    r"substance\s*use"        # "substance use history"
    r"|drug\s*use"            # "any history of drug use"
    r"|drug\s+(?:abuse|problem|habit)"
    r"|addiction"             # "... or addiction"
    r"|overdose"              # "has she ever had a drug overdose"
    r"|rehab"                 # "been in rehab or detox" (rehab, rehabilitation)
    r"|detox"                 # "... or detox"
    r"|alcohol\s*use"         # "alcohol use disorder"
    r"|alcoholism"
    r"|illicit\s+(?:drug|substance)"
    r"|injection\s+drug|intravenous\s+drug|\biv\s+drug"
    r"|heroin|cocaine|methamphetamine|cannabis|marijuana"
    r"|psychiatr"             # psychiatric / psychiatry
    r"|behavioral\s*health"
    r"|mental\s*health"
    r"|bipolar|schizophreni|\bptsd\b|post-?traumatic|psychosis"
    r"|major\s+depress|depressive\s+disorder"
    r"|suicidal"
    r"|self-?harm",
    re.IGNORECASE,
)

# Bulk-dump / exfiltration signal. A category word riding INSIDE one of these
# demands ("print the entire chart ... psychiatric history ... SSN") is the
# finding-2 attack, NOT a scoped clinical need-to-know, so it must NOT stand the
# gate down. Deliberately limited to STRONG exfiltration markers — the weak
# generic-breadth tokens ("everything", "full history", "the complete", "start to
# finish") were dropped because they legitimately attach to a scoped category ask
# ("give me the complete substance use history"), which is a real need-to-know.
_BULK_DUMP_RE = re.compile(
    r"entire chart"
    r"|whole chart"
    r"|entire record"
    r"|whole record"
    r"|complete picture"
    r"|all records"
    r"|print out"
    r"|print the (?:entire|whole|full)"
    r"|verbatim"
    r"|\bSSN\b"
    r"|social security"
    r"|insurance",
    re.IGNORECASE,
)


def question_permits_sensitive(question: str) -> bool:
    """True IFF ``question`` is a genuine scoped clinical ask about the category.

    True only when the question mentions the protected category AND does NOT also
    carry a bulk-dump / exfiltration signal. A category word inside a bulk-dump
    demand returns False (finding-2 attack). Generic breadth, benign/narrow
    questions, and empty/whitespace input all return False.
    """
    if not question or not question.strip():
        return False
    if _PERMIT_CATEGORY_RE.search(question) is None:
        return False
    # A scoped clinical need-to-know, unless the category word is riding inside a
    # bulk-dump / exfiltration demand.
    return _BULK_DUMP_RE.search(question) is None


# --- answer side: sentences that disclose protected history/events -----------

# Protected substance-use / behavioral-health *history/events*. Scoped tightly to
# avoid false positives: bare "alcohol" (swab), bare "opioid" (analgesia), bare
# "rehabilitation" (cardiac/pulmonary), bare "depression" (ST depression), the
# anesthetic "fentanyl", and MAT medication NAMES (methadone, buprenorphine,
# suboxone — an active med is need-to-know) all deliberately do NOT match.
# "rehabilitation" only matches when qualified by "drug " (a sentence that also
# names "detox" is caught by the detox pattern regardless). "psychiatric" is
# handled separately (``_PSYCH_EVENT_RE``) so it only fires on history/event
# context, never on a medication descriptor.
_SENSITIVE_RE = re.compile(
    r"overdose"                                     # drug overdose event
    r"|detox\w*"                                     # detox, detoxification
    r"|drug\s+rehab\w*"                              # drug rehab, drug rehabilitation
    r"|substance[\s-]?(?:use|abuse)"                 # substance use/-use/abuse (+ disorder)
    r"|addict(?:ion|ed)"                             # addiction, addicted
    r"|alcoholism"
    r"|alcohol\s+(?:use\s+disorder|dependence|abuse)"
    r"|opioid\s+(?:use\s+disorder|dependence|abuse)"
    r"|narcotic\s+abuse"
    r"|heroin|cocaine|methamphetamine|cannabis|marijuana"   # named illicit drugs
    r"|illicit\s+(?:drug|substance)"
    r"|injection\s+drug\s+use|intravenous\s+drug\s+use|\biv\s+drug\s+use"
    r"|suicidal"
    r"|suicide\s+attempt"
    r"|self-?harm"
    r"|behavioral\s+health"
    r"|mental\s+health"
    r"|bipolar"                                      # named behavioral-health dx
    r"|schizophreni\w*"
    r"|\bptsd\b"
    r"|post-?traumatic\s+stress"
    r"|major\s+depress\w*"                           # major depression/depressive (NOT bare "depression")
    r"|depressive\s+disorder"
    r"|psychosis",
    re.IGNORECASE,
)

# The broad adjective "psychiatric"/"psychiatry" is disclosed history ONLY when it
# sits next to an event/history noun. Requiring the pairing keeps a medication
# sentence ("... for psychiatric management, warfarin 5 mg") from being deleted
# wholesale (which would silently drop the co-located warfarin dose), while still
# catching "a prior psychiatric admission" and "psychiatric-relevant history".
# The event-context words deliberately exclude med-ish terms (management,
# medication, care, treatment, condition) so a drug line is never swallowed.
_PSYCH_EVENT_WORDS = (
    r"admission|admitted|hospitaliz\w*|inpatient|history|diagnos\w*|disorder|"
    r"illness|\bhold\b|commit\w*|evaluation|episode|ward|crisis"
)
_PSYCH_EVENT_RE = re.compile(
    rf"psychiatr\w*[\s\w,'-]{{0,40}}?\b(?:{_PSYCH_EVENT_WORDS})\b"
    rf"|\b(?:{_PSYCH_EVENT_WORDS})[\s\w,'-]{{0,40}}?psychiatr\w*",
    re.IGNORECASE,
)

# Sentence splitting, mirroring verification.py: a ``.`` flanked by digits is a
# decimal point (INR, HbA1c, doses), NOT a sentence boundary. Swap such dots for
# a placeholder before splitting and restore them after, byte-for-byte.
_DECIMAL_DOT_RE = re.compile(r"(?<=\d)\.(?=\d)")
_DECIMAL_DOT_PLACEHOLDER = "\x00"
_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]+|[^.!?]+$")


def _sentence_is_sensitive(sentence: str) -> bool:
    """True if the sentence discloses protected substance-use / behavioral history."""
    return (
        _SENSITIVE_RE.search(sentence) is not None
        or _PSYCH_EVENT_RE.search(sentence) is not None
    )


def scrub_sensitive_disclosure(question: str, answer: str) -> DisclosureScrubResult:
    """Remove protected-category history sentences unless the question asks for them.

    If ``question_permits_sensitive(question)`` is True the answer flows through
    unchanged. Otherwise every sentence that discloses substance-use /
    behavioral-health history/events is removed; if at least one is removed a
    single :data:`SENSITIVE_REDACTION_NOTICE` is appended and the result is
    marked redacted. If nothing matches, the answer is returned unchanged.

    Deterministic and idempotent: a second pass over the redacted text removes
    nothing more (the appended notice carries no category token).
    """
    if question_permits_sensitive(question):
        return DisclosureScrubResult(text=answer, redacted=False, reason="")

    protected = _DECIMAL_DOT_RE.sub(_DECIMAL_DOT_PLACEHOLDER, answer)
    fragments = [
        match.group(0).replace(_DECIMAL_DOT_PLACEHOLDER, ".")
        for match in _SENTENCE_RE.finditer(protected)
    ]

    kept = [frag for frag in fragments if not _sentence_is_sensitive(frag)]
    if len(kept) == len(fragments):
        # Nothing disclosed the protected category — leave the answer untouched.
        return DisclosureScrubResult(text=answer, redacted=False, reason="")

    remaining = "".join(kept).strip()
    text = f"{remaining} {SENSITIVE_REDACTION_NOTICE}" if remaining else SENSITIVE_REDACTION_NOTICE
    return DisclosureScrubResult(text=text, redacted=True, reason=_REASON)
