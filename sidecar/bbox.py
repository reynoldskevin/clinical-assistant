"""Deterministic citation bounding-box locator (T56 Option 1).

Maps a fact's ``source_citation`` quote onto a page's word geometry and returns
the covering box(es) — one union box per rendered line. Pure-stdlib (``re``
only): no OCR system dependency, no image libraries, no live API. The word
geometry is supplied by the caller (an injectable provider on ``/extract``), so
this module is a pure function over known pixel-space coordinates.
"""
from __future__ import annotations

import re
from typing import Any


def _normalize(tok: str) -> str:
    """Lowercase and strip non-alphanumerics (so ``"7.4%"`` -> ``"74"``)."""
    return re.sub(r"[^a-z0-9]", "", tok.lower())


def _same_line(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two words share a line iff their vertical ranges overlap."""
    return not (a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def _union_box(group: list[dict[str, Any]]) -> dict[str, Any]:
    min_x = min(w["x"] for w in group)
    min_y = min(w["y"] for w in group)
    max_x = max(w["x"] + w["w"] for w in group)
    max_y = max(w["y"] + w["h"] for w in group)
    return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}


def locate_citation_boxes(words: list[dict[str, Any]], quote: str) -> list[dict[str, Any]]:
    """Locate ``quote`` within ``words`` and return one union box per line.

    ``words`` is page geometry: ``{"text", "x", "y", "w", "h"}`` dicts in pixel
    space, in reading order. ``quote`` is the fact's ``source_citation``.

    Tokens are normalized by lowercasing and stripping non-alphanumerics; tokens
    that normalize to empty (punctuation-only) are dropped from both the quote
    and the page. The quote's normalized token sequence is matched as a
    contiguous subsequence of the page's non-empty word tokens (first match
    wins). The matched run is grouped into lines (consecutive words on the same
    line iff their vertical ranges overlap) and each group returns its union box
    in reading order. Returns ``[]`` when there is no match or nothing to match.
    """
    quote_tokens = [t for t in (_normalize(tok) for tok in quote.split()) if t]
    if not quote_tokens:
        return []

    # Keep only words whose text normalizes to a non-empty token, preserving
    # order, so punctuation-only page words don't break contiguity.
    page = [(w, _normalize(w["text"])) for w in words]
    page = [(w, norm) for (w, norm) in page if norm]
    if not page:
        return []

    n = len(quote_tokens)
    for start in range(len(page) - n + 1):
        if [norm for (_w, norm) in page[start:start + n]] == quote_tokens:
            matched = [w for (w, _norm) in page[start:start + n]]
            return _group_lines(matched)

    return []


def _group_lines(matched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    group: list[dict[str, Any]] = [matched[0]]
    for word in matched[1:]:
        if _same_line(group[-1], word):
            group.append(word)
        else:
            boxes.append(_union_box(group))
            group = [word]
    boxes.append(_union_box(group))
    return boxes
