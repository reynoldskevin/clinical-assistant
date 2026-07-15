"""Sidecar Claude agent implementing a manual tool-use loop.

The Claude message-creator and the clinical boundary caller are injected as
plain callables (constructor DI), so this module never imports the anthropic
SDK and never makes a live API call. Response objects are duck-typed to the
SDK Message shape: a ``.content`` list of blocks plus a ``.stop_reason``.

The single exposed tool, ``get_patient_summary``, deliberately takes no
patient argument: the patient is fixed for the session, and the model must
not be able to redirect the lookup to a different chart.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from citation_gate import CitationGate
from contracts import EmptyToolInput
from observability import NullObserver
from verification import (
    _DECIMAL_DOT_PLACEHOLDER,
    _DECIMAL_DOT_RE,
    _MARKER_RE,
    _SENTENCE_RE,
    VerificationGate,
)

# The sentinel ref for a verified negative ("not documented in the record").
_ABSENCE_REF = "openemr:_absence"

# Matches a fenced ```citations block and captures the JSON array inside it.
# Tolerant of trailing whitespace/newlines around the JSON payload.
_CITATIONS_BLOCK_RE = re.compile(
    r"```citations\s*\n(.*?)\n?```",
    re.DOTALL,
)

# The response object returned by the message-creator (SDK Message shape).
MessageResponse = Any

# Callable signature: message_creator(model=, max_tokens=, system=, tools=, messages=).
MessageCreator = Callable[..., MessageResponse]

# Callable signature: boundary(pid) -> dict (the patient summary).
Boundary = Callable[[int], dict[str, Any]]

# An extra tool spec: {name, description, input_schema, handler}, where
# handler(pid, tool_input) -> dict. The session pid is fixed (from the token);
# the model's tool_input is passed through but can never redirect the pid.
ToolSpec = dict[str, Any]

# Default per-turn budget on the total number of tool executions. This bounds a
# runaway chain independently of (and more strictly than) the raw iteration cap.
_DEFAULT_MAX_TOOL_CALLS = 8

def _collect_refs(data: Any) -> set[str]:
    """Pull every ``ref`` string from tool-result data.

    A tool result may be a single dict (with an optional ``"ref"`` key) or a
    list of such dicts (e.g. medication/chart rows). Tools without a ``ref``
    contribute nothing.
    """
    refs: set[str] = set()
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if isinstance(row, dict):
            ref = row.get("ref")
            if isinstance(ref, str):
                refs.add(ref)
    return refs


def _collect_data(data: Any) -> dict[str, dict[str, Any]]:
    """Map each tool-result ``ref`` to its record dict.

    Mirrors :func:`_collect_refs` but keeps the whole row keyed by its ``ref``,
    so the grounding gate's V3 contradiction check can compare a cited med's
    record against the claim made about it.
    """
    out: dict[str, dict[str, Any]] = {}
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if isinstance(row, dict):
            ref = row.get("ref")
            if isinstance(ref, str):
                out[ref] = row
    return out


_SYSTEM_PROMPT = (
    "You are a clinical assistant embedded in an electronic health record. "
    "Answer questions about the current patient concisely and accurately, "
    "using the get_patient_summary tool to retrieve the patient's chart when "
    "clinical detail is needed. Never speculate beyond the retrieved data.\n\n"
    "Ground every answer in the retrieved records. For each record you rely on, "
    "cite it inline with an [Sn] marker (S1, S2, ...) placed next to the claim "
    "it supports. Give each distinct record its own marker, and place that marker "
    "in the SAME sentence or list item as the specific record it names — e.g. "
    '"Warfarin Sodium 5 MG is active [S1]". Do NOT put a marker on a lead-in or '
    "heading that names no specific record (write a bare \"Active medications:\" "
    "with no marker, then cite each drug on its own line), and do NOT reuse one "
    "marker for several different records. "
    "Any sentence that states a specific date, count, or measured value must carry "
    "an [Sn] marker to the record it came from — never leave a dated or numeric "
    "statement uncited. When such a sentence asserts that something is NOT "
    'documented, cite it with "openemr:_absence" so the absence is grounded too. '
    "End your answer with a fenced ```citations block containing a "
    "JSON array that maps each n to the exact tool-provided ref, e.g.\n"
    "```citations\n"
    '[{"n": 1, "ref": "prescription:1"}]\n'
    "```\n"
    "When you state that something is not documented, cite it with the ref "
    '"openemr:_absence".\n'
    "When a claim rests on clinical-guideline-corpus evidence (from the "
    "evidence_retriever tool), cite it with its tool-provided guideline ref, "
    'which starts "guideline:" (patient-record refs are cited unchanged), so '
    "record facts and guideline evidence are distinguishable by the ref prefix.\n\n"
    "Data-quality honesty:\n"
    "- An empty chart section means the data is not documented, not that the "
    "finding is absent (empty != absent). Say \"not documented\"; never infer a "
    "clinical negative (e.g. do not conclude the patient has no allergies just "
    "because the allergy list is empty).\n"
    "- When a problem has no diagnosis code, or a medication has no rxnorm code, "
    "note that it is documented as free text only (uncoded), so the physician "
    "knows it is not coded.\n"
    "- Do not attempt to identify duplicate or merged patient records. That is a "
    "deterministic master-patient-index function; if asked, say you surface "
    "context but defer duplicate/merge detection to that tool.\n\n"
    "Task framing:\n"
    "- Longitudinal questions (has this been worked up before? recurrent or "
    "frequent presentations?): synthesize the PATTERN across the relevant prior "
    "encounters — what was investigated, what was found, what was done — rather "
    "than only listing that visits exist. Be explicit about which prior history "
    "you could and could not find; if a prior study or workup is not in the "
    "record, say so plainly instead of inferring one.\n"
    "- Handoff / sign-out requests: present the summary as a DRAFT for the "
    "physician to verify and own — say it is a draft to review, not an "
    "authoritative record — and flag pending or uncertain items rather than "
    "resolving them."
)


# Appended to the returned answer when the tool budget is exhausted before the
# model produced a natural end_turn — i.e. the answer is forced on partial data.
# Kept digit-free and citation-free so it never perturbs the grounding gate; it
# is attached AFTER gating and only to the returned string, not persisted history.
_TRUNCATION_NOTICE = (
    "\n\n(Partial answer: I reached my lookup limit for this question and may "
    "not have reviewed every record. Ask me to look further on any point.)"
)


# Appended to the returned answer when any tool returned an is_error result this
# turn (a boundary/handler exception or an unknown tool). Signals that the answer
# was produced despite a failed record lookup, so it may be incomplete. Kept
# digit-free and citation-free (like _TRUNCATION_NOTICE) so it never perturbs the
# grounding gate; attached AFTER gating and only to the returned string, not
# persisted history. Independent of and composable with _TRUNCATION_NOTICE.
_DEGRADED_NOTICE = (
    "\n\n(Note: one or more record lookups failed, so this answer may be "
    "incomplete. Try again, or verify against the chart.)"
)


class ClaudeAgent:
    """Runs a bounded, manual tool-use loop against an injected message-creator."""

    def __init__(
        self,
        message_creator: MessageCreator,
        boundary: Boundary,
        model: str = "claude-opus-4-8",
        max_tokens: int = 4096,
        observer: Any = None,
        extra_tools: list[ToolSpec] | None = None,
        max_tool_calls: int = _DEFAULT_MAX_TOOL_CALLS,
        correlation_id: str | None = None,
    ) -> None:
        self._message_creator = message_creator
        self._boundary = boundary
        self._model = model
        self._max_tokens = max_tokens
        self._observer = observer or NullObserver()
        self._correlation_id = correlation_id
        # Injectable tool registry keyed by name, each carrying its handler.
        self._extra_tools = list(extra_tools or [])
        # Cap on the total number of tool executions per turn. Once this many
        # tools have run, the loop stops offering tools and forces a final
        # text answer from whatever the model has already gathered.
        self._max_tool_calls = max_tool_calls

    @property
    def observer(self) -> Any:
        """The observability collector for this run (token usage, cost, tool calls)."""
        return self._observer

    @property
    def correlation_id(self) -> str | None:
        """The correlation id threaded through this agent invocation, if any."""
        return self._correlation_id

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_patient_summary",
                "description": (
                    "Retrieve a structured clinical summary of the current "
                    "patient, including demographics, active problems, "
                    "medications, allergies, and recent vitals. Takes no "
                    "arguments: the patient is fixed for this session."
                ),
                "input_schema": EmptyToolInput.model_json_schema(),
            },
            *(
                {
                    "name": spec["name"],
                    "description": spec["description"],
                    "input_schema": spec["input_schema"],
                }
                for spec in self._extra_tools
            ),
        ]

    def _handler_for(self, name: str) -> Callable[[int, dict[str, Any]], dict[str, Any]] | None:
        """Return the injected handler for ``name``, or None if not registered."""
        for spec in self._extra_tools:
            if spec["name"] == name:
                return spec["handler"]
        return None

    def _gate_final_answer(
        self,
        draft: str,
        retrieved_refs: set[str],
        retrieved_data: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        """Apply the grounding gate iff the draft used the §4 citation format.

        If ``draft`` carries a fenced ```citations block, parse it, remove the
        block from the display text, run :class:`VerificationGate`, and return
        the rendered (fabricated-stripped / ungrounded-demoted) answer. Without
        a citations block the draft is returned unchanged — legacy/unformatted
        answers are never gated.
        """
        match = _CITATIONS_BLOCK_RE.search(draft)
        if match is None:
            return draft

        try:
            citations = json.loads(match.group(1))
        except (ValueError, TypeError):
            # Malformed block: strip nothing, gate nothing, return as-is.
            return draft
        if not isinstance(citations, list):
            return draft

        display_text = (draft[: match.start()] + draft[match.end():]).strip()
        result = VerificationGate().verify(
            display_text, citations, retrieved_refs, retrieved_data
        )
        self._observer.record_verification(result["verdict"])
        rendered = result["rendered_answer"]

        # A blocked verdict replaces the unverified draft with the safe fallback;
        # it carries no surviving claims to separate, so it must be returned
        # verbatim. Running the split here would wrap the fallback under a record
        # section (the original citations still name a guideline ref), leaking the
        # split machinery onto a blocked answer.
        if result["verdict"] == "blocked":
            return rendered

        # T50 activation: when the W1-surviving citations include at least one
        # guideline ref, lift the cited claims into structured Citations and run
        # CitationGate so the answer separates patient-record facts from
        # guideline evidence. Otherwise (record-only / absence-only / no
        # guideline evidence) the W1 rendering is returned byte-for-byte.
        return self._apply_citation_split(
            rendered, citations, retrieved_refs, retrieved_data or {}
        )

    def _apply_citation_split(
        self,
        rendered: str,
        citations: list[dict[str, Any]],
        retrieved_refs: set[str],
        retrieved_data: dict[str, dict[str, Any]],
    ) -> str:
        """Compose :class:`CitationGate` onto the W1-gated ``rendered`` answer.

        The record/guideline split is only produced when at least one *surviving*
        citation (its ref grounded this turn, or the absence sentinel) is a
        ``guideline:`` ref. Without guideline evidence there is nothing to
        separate, so ``rendered`` is returned unchanged (W1 back-compat).

        Each sentence carrying a surviving ``[Sn]`` marker becomes one
        ``CitationGate`` claim, its ``Citation`` synthesized from
        ``retrieved_data`` for the cited ref (prefix -> ``source_type``, ref ->
        ``source_id``). A ref with no backing record is treated as uncited
        (``citation=None``) so the gate demotes it rather than fabricating fields.
        """
        valid_refs = set(retrieved_refs) | {_ABSENCE_REF}
        by_number = {
            c["n"]: c["ref"]
            for c in citations
            if isinstance(c, dict) and "n" in c and "ref" in c
        }
        surviving = {n: ref for n, ref in by_number.items() if ref in valid_refs}

        has_guideline = any(
            ref.startswith("guideline:") for ref in surviving.values()
        )
        if not has_guideline:
            return rendered

        claims: list[dict[str, Any]] = []
        for sentence in self._split_sentences(rendered):
            marker_numbers = [
                int(m.group(1)) for m in _MARKER_RE.finditer(sentence)
            ]
            surviving_here = [n for n in marker_numbers if n in surviving]
            if not surviving_here:
                # Non-clinical prose (or a demoted/stripped sentence): pass it
                # through as a record fact so it is not lost from the answer.
                claims.append(
                    {
                        "text": sentence.strip(),
                        "citation": self._passthrough_citation(sentence),
                    }
                )
                continue
            ref = surviving[surviving_here[0]]
            claims.append(
                {
                    "text": sentence.strip(),
                    "citation": self._citation_for(ref, retrieved_data),
                }
            )

        return CitationGate().gate(claims)["rendered_answer"]

    @staticmethod
    def _passthrough_citation(sentence: str) -> dict[str, Any]:
        """A synthetic record citation for non-cited prose kept in the answer."""
        text = sentence.strip() or "prose"
        return {
            "source_type": "record",
            "source_id": "narrative",
            "page_or_section": "narrative",
            "field_or_chunk_id": "narrative",
            "quote_or_value": text,
        }

    @staticmethod
    def _citation_for(
        ref: str,
        retrieved_data: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Synthesize a five-field Citation dict for ``ref`` from its backing row.

        Returns ``None`` (uncited -> demoted by the gate) when the ref has no
        backing record, so no field is ever fabricated. The absence sentinel is
        treated as a record citation.
        """
        record = retrieved_data.get(ref)
        source_type = "guideline" if ref.startswith("guideline:") else "record"
        if ref == _ABSENCE_REF:
            return {
                "source_type": "record",
                "source_id": ref,
                "page_or_section": "absence",
                "field_or_chunk_id": ref,
                "quote_or_value": "not documented in the record",
            }
        if record is None:
            return None

        if source_type == "guideline":
            section = record.get("citation") or ref
            chunk_id = ref.split("guideline:", 1)[1] or ref
            quote = record.get("text") or record.get("citation") or ref
            return {
                "source_type": "guideline",
                "source_id": ref,
                "page_or_section": section,
                "field_or_chunk_id": chunk_id,
                "quote_or_value": quote,
            }

        section = record.get("section") or record.get("title") or ref
        field = record.get("drug") or record.get("title") or ref
        quote = (
            record.get("drug")
            or record.get("title")
            or record.get("value")
            or ref
        )
        return {
            "source_type": "record",
            "source_id": ref,
            "page_or_section": str(section),
            "field_or_chunk_id": str(field),
            "quote_or_value": str(quote),
        }

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split ``text`` into sentences, decimal-safe (mirrors VerificationGate).

        A ``.`` flanked by digits (``2.0``) is protected before splitting and
        restored after, so clinical values are not mangled into fake sentences.
        """
        protected = _DECIMAL_DOT_RE.sub(_DECIMAL_DOT_PLACEHOLDER, text)
        out: list[str] = []
        for match in _SENTENCE_RE.finditer(protected):
            sentence = match.group(0).replace(_DECIMAL_DOT_PLACEHOLDER, ".")
            if sentence.strip():
                out.append(sentence)
        return out

    def run(self, question: str, pid: int) -> str:
        """Answer ``question`` about patient ``pid`` via the tool-use loop."""
        return self.run_turn(question, pid)[0]

    def run_turn(
        self,
        question: str,
        pid: int,
        history: list | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> tuple[str, list]:
        """Run one turn and return ``(answer, messages)``.

        Starts from ``history`` (or a fresh conversation), appends ``question``
        as the user turn, runs the same bounded tool-use loop as ``run``, and on
        the final text answer appends the assistant turn so the returned message
        list can seed the next turn. The pid is fixed for the session.

        When ``on_event`` is supplied, each tool execution emits a live status
        event ``{"type": "tool", "name": <tool>, "ok": <bool>}`` (success,
        failure, and unknown-tool alike) after it is recorded. The answer text is
        NEVER emitted through ``on_event`` — it is returned buffered and gated as
        today, so no unverified clinical content leaks through the status
        channel. ``on_event=None`` reproduces today's behaviour byte-for-byte.
        """
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": question})

        # Cumulative tool executions across the whole turn (every tool_result
        # appended counts once — success, failure, unknown, injected alike).
        tool_calls_made = 0
        # Whether ANY tool returned an is_error result this turn (boundary
        # exception, injected-handler exception, or unknown tool). Drives the
        # partial-failure disclosure at the final-answer branch.
        tool_failure_seen = False
        # Every ``ref`` value seen in tool-result data this turn. Used by the
        # grounding gate to distinguish cited-from-record from fabricated refs.
        retrieved_refs: set[str] = set()
        # Every ``ref -> record`` seen in tool-result data this turn. Feeds the
        # gate's V3 contradiction check (a cited med must be that record).
        retrieved_data: dict[str, dict[str, Any]] = {}
        # Derive the iteration bound from the budget so the final no-tools call
        # (made once the budget is spent) always fits before the safety cap.
        max_iterations = self._max_tool_calls + 2

        for _ in range(max_iterations):
            # Offer tools only while under budget; once spent, pass an empty
            # list so the model cannot call more tools and must answer as text.
            offer_tools = self._tools() if tool_calls_made < self._max_tool_calls else []
            resp = self._message_creator(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_SYSTEM_PROMPT,
                tools=offer_tools,
                messages=messages,
            )

            usage = getattr(resp, "usage", None)
            self._observer.record_model_response(
                getattr(usage, "input_tokens", 0) if usage else 0,
                getattr(usage, "output_tokens", 0) if usage else 0,
            )

            tool_uses = [
                block
                for block in resp.content
                if getattr(block, "type", None) == "tool_use"
            ]

            if not tool_uses:
                draft = "".join(
                    block.text
                    for block in resp.content
                    if getattr(block, "type", None) == "text"
                )
                answer = self._gate_final_answer(draft, retrieved_refs, retrieved_data)
                # Retain the final assistant turn so the next turn has context.
                # Store the extracted text (not the raw SDK blocks) so the
                # persisted history is plain, JSON-serializable data. This
                # happens AFTER the last creator call, so it adds no creator call
                # and does not alter any earlier ``creator.calls`` entry.
                # Persist the un-suffixed gated answer so re-seeding a future turn
                # never accumulates truncation notices.
                messages.append({"role": "assistant", "content": answer})
                # Completeness-boundary disclosure: if this final answer was
                # forced because the tool budget was spent (rather than a natural
                # end_turn under budget), tell the caller. The notice is appended
                # to the RETURNED string only (after gating, so grounding is
                # untouched), and exactly one truncation event is emitted.
                if tool_calls_made >= self._max_tool_calls:
                    self._observer.record_truncated()
                    if on_event is not None:
                        on_event({"type": "truncated", "reason": "tool_budget"})
                    answer = answer + _TRUNCATION_NOTICE
                # Partial-failure disclosure: independent of and composable with
                # the truncation notice above. If any tool returned is_error this
                # turn, disclose that the answer may be incomplete. Appended to the
                # RETURNED string only (after gating) and one degraded event emitted.
                if tool_failure_seen:
                    self._observer.record_degraded()
                    if on_event is not None:
                        on_event({"type": "degraded", "reason": "tool_failure"})
                    answer = answer + _DEGRADED_NOTICE
                return answer, messages

            messages.append({"role": "assistant", "content": resp.content})

            tool_results: list[dict[str, Any]] = []
            for block in tool_uses:
                # Every handled tool_use block counts against the budget.
                tool_calls_made += 1
                if block.name == "get_patient_summary":
                    # Fixed session pid — ignore any model-supplied input.
                    try:
                        summary = self._boundary(pid)
                    except Exception:
                        # Record the failure and feed an error result back so the
                        # model can respond; the loop must not crash.
                        tool_failure_seen = True
                        self._observer.record_tool_call("get_patient_summary", False)
                        if on_event is not None:
                            on_event({"type": "tool", "name": block.name, "ok": False})
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": "Failed to retrieve the patient summary.",
                            }
                        )
                    else:
                        retrieved_refs.update(_collect_refs(summary))
                        retrieved_data.update(_collect_data(summary))
                        self._observer.record_tool_call("get_patient_summary", True)
                        if on_event is not None:
                            on_event({"type": "tool", "name": block.name, "ok": True})
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(summary),
                            }
                        )
                elif (handler := self._handler_for(block.name)) is not None:
                    # An injected chart tool. The session pid is fixed; the model
                    # supplies only tool_input. Failures become a tool error, not
                    # a crash — mirroring the summary error path above.
                    try:
                        result = handler(pid, block.input)
                    except Exception:
                        tool_failure_seen = True
                        self._observer.record_tool_call(block.name, False)
                        if on_event is not None:
                            on_event({"type": "tool", "name": block.name, "ok": False})
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": f"Failed to run tool: {block.name}",
                            }
                        )
                    else:
                        retrieved_refs.update(_collect_refs(result))
                        retrieved_data.update(_collect_data(result))
                        self._observer.record_tool_call(block.name, True)
                        if on_event is not None:
                            on_event({"type": "tool", "name": block.name, "ok": True})
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            }
                        )
                else:
                    tool_failure_seen = True
                    self._observer.record_tool_call(block.name, False)
                    if on_event is not None:
                        on_event({"type": "tool", "name": block.name, "ok": False})
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": True,
                            "content": f"Unknown tool: {block.name}",
                        }
                    )

            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(
            f"Tool-use loop exceeded {max_iterations} iterations without a final answer."
        )
