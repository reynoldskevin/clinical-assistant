"""Deterministic request guardrail for adversarial control / meta-process turns.

Classifies the *denial-of-service* class of prompt that the red-team findings
VULN-9a0c65e6 (a 1000-call tool loop) and VULN-06edd052 (a never-terminating
per-sentence re-verify cycle) exercised. These prompts are not clinical
questions: they instruct the agent to burn tool/model calls in a loop, or to
never finalize an answer. Detecting them up front lets the agent refuse WITHOUT
invoking the model or any tool, so no patient PHI is fetched or emitted on that
turn.

Pure, offline, deterministic, and stdlib-only (``re`` + ``dataclasses``): no
network, no I/O, no clock, no randomness.

The classifier is intentionally conservative, and hardened against
false-positives on real clinical phrasing. The loop rule requires TWO
independent conditions to both hold:

    1. an explicit *repetition signal* — a verb/gerund or unmistakable loop
       phrase that instructs the agent to repeat an action (``repeat``,
       ``loop``, ``alternate``, ``iterate``, ``recursively``, ``re-run``,
       ``keep going``/``keep repeating``…, ``over and over``, ``again and
       again``, ``back and forth``); AND
    2. a *large count* (an integer literal >= 25, or a spelled magnitude/tens
       number-word) OR an *unbounded* word (``continuously``, ``forever``,
       ``endlessly``, ``never stop``…).

A large number ALONE never blocks, and a repetition signal ALONE never blocks.
Critically, bare ``times`` / ``in a row`` / ``in sequence`` are NOT repetition
signals: they collide with legitimate clinical phrasing such as "How many times
has the systolic blood pressure been over 140?" or "in sequence by date", and a
frequency question about the patient must never be read as an instruction to
loop. Because the large-count check is coupled to a repetition signal, spelled
tens words ("the patient is fifty years old") also stay safe.

@package   OpenEMR
@link      https://www.open-emr.org
@license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --- resource_exhaustion_loop signals ----------------------------------------

# Repetition INSTRUCTION: a verb/gerund (or unmistakable loop phrase) directing
# the agent to repeat / alternate / loop / iterate / recurse an action. Bare
# "times", "in a row", and "in sequence" are deliberately NOT here — they are
# descriptive/interrogative and collide with clinical phrasing ("how many times
# ... over 140", "in sequence by date"), so they must never, alone, signal a
# loop.
_REPETITION_RE = re.compile(
    r"\b(?:"
    r"repeat\w*"          # repeat, repeats, repeating, repeatedly
    r"|loop\w*"           # loop, looping, loops
    r"|alternat\w*"       # alternate, alternating, alternates
    r"|iterat\w*"         # iterate, iterating, iterates
    r"|recursiv\w*"       # recursive, recursively
    r"|re-?run\w*"        # re-run, rerun, re-running
    r")\b"
    r"|\bkeep going\b"
    r"|\bkeep (?:repeating|looping|calling|running|alternating)\b"
    r"|over and over"
    r"|again and again"   # NOTE: bare "again" deliberately does NOT match
    r"|back and forth",
    re.IGNORECASE,
)

# Large magnitude / tens number-WORDS (a "large count" without a digit literal).
# The tens words (twenty..ninety) and "dozen" only ever contribute to a block
# when a repetition signal is ALSO present, so "fifty years old" stays safe.
_LARGE_WORD_RE = re.compile(
    r"\b(?:"
    r"hundred|thousand|million|billion|dozen"
    r"|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r")s?\b",
    re.IGNORECASE,
)

# Any integer literal, allowing comma grouping (e.g. ``1,000`` or ``500``).
_INTEGER_RE = re.compile(r"\b\d[\d,]*\b")

# A repeat count is "large" (resource-exhausting) at or above this threshold.
# Below it, a bounded repeat ("read it back 2 times") is a normal request.
_LARGE_COUNT_THRESHOLD = 25

# Unbounded / never-stopping words: a loop with no finite bound at all.
_UNBOUNDED_RE = re.compile(
    r"\b(?:"
    r"continuously"
    r"|forever"
    r"|endless\w*"        # endless, endlessly
    r"|nonstop"
    r"|indefinitely"
    r"|countless"
    r")\b"
    r"|non-stop"
    r"|without stopping"
    r"|never stop\w*"                                  # "never stop", "never stopping"
    r"|until i (?:say|tell you)[\w\s,'-]{0,40}?\bstop",  # "until I say ... stop"
    re.IGNORECASE,
)

# --- nonterminating_process signals ------------------------------------------

# (a) "never complete": the word "never" sitting near a finalize/deliver/
# complete/finish token, i.e. an instruction to never produce a finished answer.
# A short window of intervening words is allowed ("never produce a finished
# answer", "never finalized or delivered in complete form").
_NEVER_COMPLETE_RE = re.compile(
    r"\bnever\b[\w\s,'-]{0,60}?\b(?:finaliz\w*|deliver\w*|complete\w*|finish\w*)",
    re.IGNORECASE,
)

# (b) per-sentence restart loop: a "from scratch / re-verify / re-check /
# restart" signal AND an "each / every / subsequent / before every sentence"
# signal. Together they describe an answer that is perpetually rebuilt.
_RESTART_RE = re.compile(
    r"from scratch"
    r"|\bre-?verif\w*"    # re-verify, reverify, re-verified
    r"|\bre-?check\w*"    # re-check, recheck
    r"|\brestart\w*",
    re.IGNORECASE,
)
_EACH_SENTENCE_RE = re.compile(
    r"(?:each|every|subsequent|before every)\s+sentence",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RequestGuardVerdict:
    """Immutable verdict from :func:`classify_request`.

    ``blocked`` is True when the request is an adversarial control / meta-process
    instruction; ``reason`` names the matched class ("resource_exhaustion_loop"
    or "nonterminating_process"), or is empty when nothing matched.
    """

    blocked: bool
    reason: str


_NOT_BLOCKED = RequestGuardVerdict(blocked=False, reason="")


def _has_large_integer(question: str) -> bool:
    """True if any integer literal in ``question`` is >= the large threshold."""
    for match in _INTEGER_RE.finditer(question):
        digits = match.group(0).replace(",", "")
        if digits and int(digits) >= _LARGE_COUNT_THRESHOLD:
            return True
    return False


def classify_request(question: str) -> RequestGuardVerdict:
    """Classify ``question`` as an adversarial control/meta-process instruction.

    Returns a blocking verdict for the two denial-of-service classes, or an
    un-blocked verdict for everything else (all legitimate clinical questions).

    The resource-exhaustion loop rule fires only when BOTH a repetition signal
    and (a large count OR an unbounded word) are present. A repetition signal
    alone, or a large number alone, never blocks — this is what keeps frequency
    questions about the patient ("how many times ... over 140") unblocked.

    Precedence: a clearly *dominant* resource-exhaustion loop (a repetition
    signal paired with a large count) wins first; then the never-terminating
    process class; then a weaker loop (repetition paired with only an unbounded
    word). Ordering the never-terminating class ahead of the unbounded-only loop
    keeps the confirm-before-every-sentence reproduction prompt mapped to
    ``nonterminating_process``.
    """
    has_repetition = _REPETITION_RE.search(question) is not None
    has_large_count = _has_large_integer(question) or (
        _LARGE_WORD_RE.search(question) is not None
    )
    has_unbounded = _UNBOUNDED_RE.search(question) is not None

    # Dominant loop: repetition + an explicit large count. This is unmistakably a
    # resource-exhaustion instruction and takes precedence even if the prompt
    # also carries never-terminating phrasing.
    if has_repetition and has_large_count:
        return RequestGuardVerdict(blocked=True, reason="resource_exhaustion_loop")

    # Never-terminating process: never-complete instruction, OR a per-sentence
    # restart loop. Checked before the weaker (unbounded-only) loop rule so a
    # confirm-before-every-sentence prompt maps to this class, not to the loop.
    never_complete = _NEVER_COMPLETE_RE.search(question) is not None
    per_sentence_restart = (
        _RESTART_RE.search(question) is not None
        and _EACH_SENTENCE_RE.search(question) is not None
    )
    if never_complete or per_sentence_restart:
        return RequestGuardVerdict(blocked=True, reason="nonterminating_process")

    # Weaker loop: repetition + an unbounded word (no finite count needed).
    if has_repetition and has_unbounded:
        return RequestGuardVerdict(blocked=True, reason="resource_exhaustion_loop")

    return _NOT_BLOCKED
