"""Regenerate the synthetic medication-list demo fixture as a TEXT-based PDF.

A text PDF (not a raster) so pdf.js can read its text layer (getTextContent) and
the card can derive per-word geometry client-side and locate citation boxes on the
actual rendered page (T56h) — no server geometry fixture, works for any text PDF.
Each medication is written as its own text run. All content is synthetic; NO PHI.

Run (needs fpdf2):  python generate_medication_list.py
"""
import os

from fpdf import FPDF

_HERE = os.path.dirname(os.path.abspath(__file__))

MEDICATIONS = [
    "Lisinopril 10 mg PO once daily",
    "Metformin 500 mg PO twice daily",
    "Atorvastatin 20 mg PO at night",
]


def main() -> None:
    pdf = FPDF(unit="pt", format=(1000, 1400))
    pdf.add_page()
    pdf.set_font("helvetica", "B", 42)
    pdf.text(60, 100, "MEDICATION LIST")
    pdf.set_font("helvetica", "", 20)
    pdf.text(60, 140, "SYNTHETIC RECORD - NO PHI")
    pdf.line(60, 160, 940, 160)
    pdf.set_font("helvetica", "B", 26)
    pdf.text(60, 220, "Current medications:")
    y = 280
    pdf.set_font("helvetica", "", 26)
    for medication in MEDICATIONS:
        pdf.text(80, y, f"- {medication}")
        y += 60
    pdf.output(os.path.join(_HERE, "synthetic_medication_list.pdf"))
    print("wrote synthetic_medication_list.pdf (text-based)")


if __name__ == "__main__":
    main()
