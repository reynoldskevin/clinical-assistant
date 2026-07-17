"""Regenerate the synthetic lab-report demo fixture (raster PDF + word geometry).

Renders a legible lab report as a PIL image (so a VLM can read it), captures each
word's box (top-down pixel space), saves the image AS a single-page PDF (pdf.js
renders it back to the same image, so the citation overlay lines up), and emits the
matching geometry JSON. All content is synthetic; NO PHI.

Run (needs Pillow + a TTF font):  python generate_lab_report.py
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
_FONT_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# label/value lines mapping 1:1 to LabFact fields.
FIELDS = [
    ("Test name", "Hemoglobin A1c"),
    ("Result", "7.4 %"),
    ("Reference range", "4.0-5.6 %"),
    ("Collection date", "2026-05-01"),
    ("Flag", "High"),
]


def main() -> None:
    W, H, margin = 1000, 1400, 60
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(_FONT_B, 42)
    label = ImageFont.truetype(_FONT_B, 26)
    value = ImageFont.truetype(_FONT, 26)
    words = []

    def draw_words(text, x0, y):
        x = x0
        for tok in text.split():
            l, t, r, b = d.textbbox((x, y), tok, font=value)
            d.text((x, y), tok, font=value, fill="black")
            words.append({"text": tok, "x": int(l), "y": int(t), "w": int(r - l), "h": int(b - t)})
            x = r + d.textlength(" ", font=value)

    y = margin
    d.text((margin, y), "LABORATORY REPORT", font=title, fill="black")
    y += 52
    d.text((margin, y), "SYNTHETIC RECORD - NO PHI", font=ImageFont.truetype(_FONT, 20), fill="black")
    y += 44
    d.line([(margin, y), (W - margin, y)], fill="black", width=2)
    y += 34
    for name, val in FIELDS:
        d.text((margin, y), name + ":", font=label, fill="black")
        y += 34
        draw_words(val, margin + 20, y)
        y += 34 + 20

    img.save(os.path.join(_HERE, "synthetic_lab_report_demo.pdf"), "PDF", resolution=72.0)
    json.dump({"page_width": W, "page_height": H, "words": words},
              open(os.path.join(_HERE, "synthetic_lab_geometry.json"), "w"), indent=1)
    print(f"wrote synthetic_lab_report_demo.pdf + geometry ({len(words)} words)")


if __name__ == "__main__":
    main()
