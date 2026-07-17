"""Flag-gated demo word-geometry provider for the citation-overlay feature.

The production `/extract` route ships NO word-geometry provider, so the card draws
no citation overlay by default (T56 option 1 — deterministic locator on known
geometry, live geometry source left unwired). This module makes the overlay
VIEWABLE for the synthetic demo: when ``OE_AI_AGENT_BBOX_DEMO`` is enabled, it
serves committed word geometry for the synthetic demo documents (the intake form
and the lab report) so an upload of either renders the overlay. It is off by
default and never affects real uploads (only the known doc types, only under the
flag).

Each geometry fixture was generated from the same layout + font as the committed
demo document, so the boxes land on the real values. NO PHI — the documents are
synthetic.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

_DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "documents")
_ENABLED_VALUES = {"1", "true", "yes", "on"}

# doc_type -> committed geometry fixture ({page_width, page_height, words}).
_GEOMETRY_FIXTURES = {
    "intake_form": "synthetic_intake_geometry.json",
    "lab_pdf": "synthetic_lab_geometry.json",
}


def _demo_enabled() -> bool:
    return os.environ.get("OE_AI_AGENT_BBOX_DEMO", "").strip().lower() in _ENABLED_VALUES


def demo_geometry(pid: int, document_id: int, doc_type: str) -> Optional[dict[str, Any]]:
    """Return committed demo word geometry for ``doc_type``, or ``None``.

    Yields ``{words, page_width, page_height}`` for a known demo doc type
    (``intake_form`` / ``lab_pdf``) only when the demo flag is set — otherwise
    ``None`` (production default), so a real upload never gets synthetic geometry.
    """
    if not _demo_enabled():
        return None
    fixture = _GEOMETRY_FIXTURES.get(doc_type)
    if fixture is None:
        return None
    with open(os.path.join(_DOCS_DIR, fixture)) as handle:
        return json.load(handle)


def intake_demo_geometry(pid: int, document_id: int, doc_type: str) -> Optional[dict[str, Any]]:
    """Intake-only demo geometry (kept for existing callers); see ``demo_geometry``."""
    if doc_type != "intake_form":
        return None
    return demo_geometry(pid, document_id, doc_type)
