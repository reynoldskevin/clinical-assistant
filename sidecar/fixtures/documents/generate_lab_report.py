"""Regenerate the synthetic lab-report demo fixture as a TEXT-based PDF.

A text PDF (not a raster) so pdf.js can read its text layer (getTextContent) and
the card can derive per-word geometry client-side and locate citation boxes on the
actual rendered page (T56h) — no server geometry fixture, works for any text PDF.
Each field value is written as its own text run. All content is synthetic; NO PHI.

Run (needs fpdf2):  python generate_lab_report.py
"""
import os

from fpdf import FPDF

_HERE = os.path.dirname(os.path.abspath(__file__))

FIELDS = [
    ("Test name", "Hemoglobin A1c"),
    ("Result", "7.4 %"),
    ("Reference range", "4.0-5.6 %"),
    ("Collection date", "2026-05-01"),
    ("Flag", "High"),
]


def main() -> None:
    pdf = FPDF(unit="pt", format=(1000, 1400))
    pdf.add_page()
    pdf.set_font("helvetica", "B", 42)
    pdf.text(60, 100, "LABORATORY REPORT")
    pdf.set_font("helvetica", "", 20)
    pdf.text(60, 140, "SYNTHETIC RECORD - NO PHI")
    pdf.line(60, 160, 940, 160)
    y = 220
    for label, value in FIELDS:
        pdf.set_font("helvetica", "B", 26)
        pdf.text(60, y, f"{label}:")
        pdf.set_font("helvetica", "", 26)
        pdf.text(80, y + 40, value)
        y += 100
    pdf.output(os.path.join(_HERE, "synthetic_lab_report_demo.pdf"))
    print("wrote synthetic_lab_report_demo.pdf (text-based)")


if __name__ == "__main__":
    main()
