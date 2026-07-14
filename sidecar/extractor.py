"""VLM document extractor: stored document -> strict LabFact / IntakeFact.

Claude vision reads a document that the T46 upload path stored and that is
fetched back through the pid-scoped read boundary (``get_document`` -> base64
content), and returns a STRICT ``LabFact`` / ``IntakeFact``.

The Pydantic schema is the source of truth: raw VLM output is validated via
``Model.model_validate(...)`` before any downstream use and never bypasses the
contract. A missing-required or hallucinated-extra field RAISES ``ValidationError``
(the raise IS the "schema is source of truth" guarantee — it is not caught here).
Unsupported / low-confidence fields are flagged in ``unsupported_fields`` and left
``null``, never invented.

Sidecar-only, SDK-free: the VLM (message-creator) and the chart boundary are
injected. The anthropic SDK is never imported here — mirroring ``factory.py``,
this module stays importable without the SDK installed. The message-creator is
the same injectable callable ``factory.build_message_creator`` returns; it yields
an SDK-shaped Message with ``.content`` blocks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from contracts import IntakeFact, LabFact

# doc_type -> (contract model, human-readable label for the extraction prompt)
_CONTRACTS: dict[str, type[LabFact] | type[IntakeFact]] = {
    "lab_pdf": LabFact,
    "intake_form": IntakeFact,
}

# The fields the VLM must return for each contract, embedded in the prompt so the
# model knows exactly what JSON envelope to produce.
_DOC_INSTRUCTIONS: dict[str, str] = {
    "lab_pdf": (
        "This is a laboratory report. Extract a SINGLE lab result as these fields: "
        "test_name, value, unit, reference_range, collection_date, abnormal_flag, "
        "source_citation."
    ),
    "intake_form": (
        "This is a patient intake form. Extract these fields: demographics, "
        "chief_concern, current_medications, allergies, family_history, "
        "source_citation."
    ),
}

_MAX_TOKENS = 2048


@dataclass(frozen=True)
class ExtractionResult:
    """Validated extraction outcome.

    ``fact`` is a validated ``LabFact`` / ``IntakeFact`` instance (already through
    the strict contract). ``telemetry()`` returns ONLY non-PHI counters — safe to
    log; it carries no extracted value, citation text, or document bytes.
    """

    doc_type: str
    confidence: float
    unsupported_fields: list[str]
    fact: LabFact | IntakeFact

    def telemetry(self) -> dict[str, Any]:
        """Return a PHI-free, log-safe summary of this extraction.

        Contains only the doc type, the confidence score, and counts — never an
        extracted value, a citation, or the base64 blob.
        """
        return {
            "doc_type": self.doc_type,
            "confidence": self.confidence,
            "field_count": len(type(self.fact).model_fields),
            "unsupported_count": len(self.unsupported_fields),
        }


def _strip_json_fences(text: str) -> str:
    """Strip a leading/trailing ```json ... ``` fence if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    # drop the opening fence line (``` or ```json) and a trailing ``` line
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _content_block(mimetype: str, document_data: str) -> dict[str, Any]:
    """Build the Anthropic content block carrying the base64 document bytes.

    An ``image`` block for image mimetypes, a ``document`` block for
    application/pdf. Either way the base64 string appears verbatim in the
    ``messages`` payload.
    """
    if mimetype == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": document_data,
            },
        }
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mimetype,
            "data": document_data,
        },
    }


def attach_and_extract(
    patient_id: int,
    document_id: int,
    doc_type: str,
    *,
    chart_boundary: Any,
    message_creator: Callable[..., Any],
    model: str = "claude-opus-4-8",
) -> ExtractionResult:
    """Fetch a stored document pid-scoped and extract a strict fact from it.

    Reads the document through the pid-scoped boundary, sends its base64 bytes to
    the VLM as a vision message, validates the returned envelope's ``fact`` against
    the doc-type contract, and returns an :class:`ExtractionResult`.
    """
    contract = _CONTRACTS.get(doc_type)
    if contract is None:
        raise ValueError(f"Unsupported doc_type: {doc_type}")

    doc = chart_boundary.get_document(patient_id, document_id)
    mimetype = doc["mimetype"]
    document_data = doc["document_data"]

    instruction = _DOC_INSTRUCTIONS[doc_type]
    system = (
        "You are a clinical document extractor. Read the attached document and "
        "return ONLY a JSON envelope of the exact shape "
        '{"confidence": <0..1>, "unsupported_fields": [<field names you could '
        'not ground>], "fact": {<the requested fields>}}. '
        "NEVER invent an ungrounded value: if you cannot ground a field in the "
        "document, set it to null and list its name in unsupported_fields. "
        "Always include a source_citation that points to where in the document "
        "the facts came from. Return the JSON and nothing else."
    )

    messages = [
        {
            "role": "user",
            "content": [
                _content_block(mimetype, document_data),
                {"type": "text", "text": instruction},
            ],
        }
    ]

    response = message_creator(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=messages,
    )

    text = next(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    )
    envelope = json.loads(_strip_json_fences(text))

    # Schema is the source of truth: a missing-required or hallucinated-extra
    # field raises ValidationError here. Do NOT catch it — the raise is the guarantee.
    fact = contract.model_validate(envelope["fact"])

    return ExtractionResult(
        doc_type=doc_type,
        confidence=float(envelope["confidence"]),
        unsupported_fields=list(envelope.get("unsupported_fields", [])),
        fact=fact,
    )
