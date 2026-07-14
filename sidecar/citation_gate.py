"""Citation contract + record/evidence separation gate (T50).

Every clinical claim in a final answer must carry a machine-readable citation
so the reader can trace the assertion back to its origin. This module defines
that contract (:class:`Citation`) and a deterministic gate (:class:`CitationGate`)
that:

* validates each claim's citation through the strict :class:`Citation` model —
  a malformed/incomplete citation dict is a *contract violation* and raises
  ``pydantic.ValidationError`` (it is never silently downgraded to "uncited");
* routes each cited claim by ``source_type`` into either the patient-record
  bucket (``record_facts``) or the guideline-evidence bucket
  (``guideline_evidence``);
* demotes any *uncited* claim (``citation is None``): it raises an
  ``uncited_claim`` flag, marks the text with :data:`DEMOTION_NOTE`, and refuses
  to surface it as a clean grounded fact;
* renders an answer that separates the two kinds under distinct section headers,
  the patient-record section always before the guideline-evidence section.

This gate *composes* with the Week 1 :class:`verification.VerificationGate` — it
does not replace it. Like that gate it is pure and deterministic (stdlib +
pydantic only, no network, no I/O). Verdict shape mirrors the W1 gate:
``pass`` when there are no flags, ``pass_with_flags`` when claims were demoted.
``blocked`` is a permitted verdict value but not produced by the current
(demote-only) constraint set.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Citation ``source_type`` values: which corpus a claim is grounded in.
SOURCE_RECORD = "record"
SOURCE_GUIDELINE = "guideline"

# Distinct, human-readable section headers for the rendered answer. Record facts
# are presented before guideline evidence (stable ordering).
RECORD_SECTION_HEADER = "## Patient record"
GUIDELINE_SECTION_HEADER = "## Guideline evidence"

# Stable marker appended to any uncited claim so it can never masquerade as a
# grounded fact wherever it surfaces.
DEMOTION_NOTE = " (uncited — not grounded in the record)"


class Citation(BaseModel):
    """Machine-readable citation carried by every clinical claim.

    STRICT contract (``extra="forbid"``): all five fields are required and
    non-empty (``min_length=1``). Unknown fields are rejected, so a claim cannot
    smuggle in extra provenance the gate does not understand.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    page_or_section: str = Field(min_length=1)
    field_or_chunk_id: str = Field(min_length=1)
    quote_or_value: str = Field(min_length=1)


class CitationGate:
    """Validates citations, routes cited claims, demotes uncited ones."""

    def gate(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
        """Gate ``claims`` into routed buckets and a rendered answer.

        Each claim is ``{"text": str, "citation": <dict | Citation | None>}``.
        A dict citation is validated through :class:`Citation` (a contract
        violation raises ``pydantic.ValidationError``, which propagates); a
        :class:`Citation` instance is accepted as-is; ``None`` means uncited.

        Returns ``{"verdict", "flags", "record_facts", "guideline_evidence",
        "rendered_answer"}``. ``verdict`` is ``"pass"`` when ``flags`` is empty,
        else ``"pass_with_flags"``.
        """
        flags: list[dict[str, Any]] = []
        record_facts: list[str] = []
        guideline_evidence: list[str] = []
        demoted: list[str] = []

        for claim in claims:
            text = claim["text"]
            citation = self._parse_citation(claim.get("citation"))

            if citation is None:
                flags.append(
                    {
                        "code": "uncited_claim",
                        "text": text,
                        "action": "demoted",
                    }
                )
                demoted.append(text + DEMOTION_NOTE)
                continue

            if citation.source_type == SOURCE_GUIDELINE:
                guideline_evidence.append(text)
            else:
                record_facts.append(text)

        verdict = "pass" if not flags else "pass_with_flags"
        rendered_answer = self._render(record_facts, guideline_evidence, demoted)

        return {
            "verdict": verdict,
            "flags": flags,
            "record_facts": record_facts,
            "guideline_evidence": guideline_evidence,
            "rendered_answer": rendered_answer,
        }

    @staticmethod
    def _parse_citation(citation: Any) -> Citation | None:
        """Coerce a claim's citation field into a :class:`Citation` or ``None``.

        A ``dict`` is validated through the strict model (raising on a contract
        violation — never caught here). A :class:`Citation` instance passes
        through. ``None`` denotes an uncited claim.
        """
        if citation is None:
            return None
        if isinstance(citation, Citation):
            return citation
        return Citation(**citation)

    @staticmethod
    def _render(
        record_facts: list[str],
        guideline_evidence: list[str],
        demoted: list[str],
    ) -> str:
        """Render the separated answer: record section, then guideline, then demoted."""
        sections: list[str] = []
        if record_facts:
            sections.append(RECORD_SECTION_HEADER + "\n" + "\n".join(record_facts))
        if guideline_evidence:
            sections.append(
                GUIDELINE_SECTION_HEADER + "\n" + "\n".join(guideline_evidence)
            )
        if demoted:
            sections.append("\n".join(demoted))
        return "\n\n".join(sections)
