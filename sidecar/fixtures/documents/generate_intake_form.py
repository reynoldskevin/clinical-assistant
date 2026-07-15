"""Regenerate the synthetic intake-form fixture (a legible PNG the VLM can read).

The extractor (``extractor.attach_and_extract`` for ``doc_type=intake_form``)
sends this image to Claude vision and validates the result against the strict
``IntakeFact`` contract. The fixture must therefore be a REAL, readable form —
an earlier 1x1-pixel placeholder made the Anthropic API reject it with
"Could not process image", so live auto-extract failed. All content is
synthetic; NO PHI.

Run:  python sidecar/fixtures/documents/generate_intake_form.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT = os.path.join(_HERE, "synthetic_intake_form.png")
_FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
_FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# Synthetic intake content — maps 1:1 to the IntakeFact fields.
_FIELDS = [
    ("Patient name", "Jordan A. Rivera"),
    ("Date of birth", "1968-03-12"),
    ("Sex", "Female"),
    ("Chief concern", "Intermittent chest tightness and shortness of breath for 2 weeks."),
    ("Current medications", "Lisinopril 10 mg once daily; Metformin 500 mg twice daily; "
                            "Atorvastatin 20 mg at night."),
    ("Allergies", "Penicillin (rash)."),
    ("Family history", "Father: myocardial infarction at age 60. Mother: type 2 diabetes."),
]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _wrap(draw, text, font, max_width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def main() -> None:
    W, H, margin = 1000, 1400, 60
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    title = _font(_FONT_BOLD, 42)
    label = _font(_FONT_BOLD, 26)
    value = _font(_FONT, 26)

    y = margin
    d.text((margin, y), "PATIENT INTAKE FORM", font=title, fill="black")
    y += 52
    d.text((margin, y), "SYNTHETIC RECORD — NO PHI", font=_font(_FONT, 20), fill="black")
    y += 44
    d.line([(margin, y), (W - margin, y)], fill="black", width=2)
    y += 34

    for name, val in _FIELDS:
        d.text((margin, y), f"{name}:", font=label, fill="black")
        y += 34
        for line in _wrap(d, val, value, W - 2 * margin - 20):
            d.text((margin + 20, y), line, font=value, fill="black")
            y += 34
        y += 20

    img.save(_OUT, "PNG")
    print(f"wrote {_OUT} ({os.path.getsize(_OUT)} bytes, {W}x{H})")


if __name__ == "__main__":
    main()
