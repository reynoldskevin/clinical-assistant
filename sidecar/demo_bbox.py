"""Flag-gated demo word-geometry provider for the citation-overlay feature.

The production `/extract` route ships NO word-geometry provider, so the card draws
no citation overlay by default (T56 option 1 — deterministic locator on known
geometry, live geometry source left unwired). This module makes the overlay
VIEWABLE for the synthetic demo: when ``OE_AI_AGENT_BBOX_DEMO`` is enabled, it
serves committed word geometry for the synthetic intake form so an upload of that
form renders the overlay. It is off by default and never affects real uploads
(only ``intake_form``, only under the flag).

The geometry fixture (`fixtures/documents/synthetic_intake_geometry.json`) was
generated from the same layout + font as the committed synthetic intake PNG, so
the boxes land on the real values. NO PHI — the form is synthetic.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

_GEOMETRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "documents",
    "synthetic_intake_geometry.json",
)
_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _demo_enabled() -> bool:
    return os.environ.get("OE_AI_AGENT_BBOX_DEMO", "").strip().lower() in _ENABLED_VALUES


def intake_demo_geometry(pid: int, document_id: int, doc_type: str) -> Optional[dict[str, Any]]:
    """Return committed intake-form word geometry, or ``None``.

    Yields ``{words, page_width, page_height}`` only for ``intake_form`` uploads
    and only when the demo flag is set — otherwise ``None`` (production default),
    so a real upload never gets synthetic geometry.
    """
    if not _demo_enabled() or doc_type != "intake_form":
        return None
    with open(_GEOMETRY_PATH) as handle:
        return json.load(handle)
