"""Produce a degraded ("noisy scan") variant of the matching intake form.

T63 (extraction robustness) hardened the extractor against degraded / rotated /
noisy scans. This renders a visibly bad phone-scan version of
``synthetic_intake_form_match.png`` — skewed, low-resolution, speckled with
sensor noise and softened — while keeping the identity block legible so the VLM
still extracts structured facts (and the identity still MATCHES pid 1, so the
wrong-chart banner does not fire and muddy the demo point).

Regenerate with a Pillow-equipped interpreter:
    python degrade_scan.py
"""

import os

from PIL import Image, ImageFilter

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "synthetic_intake_form_match.png")
_DST = os.path.join(_HERE, "synthetic_intake_form_noisy.png")


def _degrade(src: str, dst: str) -> None:
    base = Image.open(src).convert("RGB")
    w, h = base.size

    # 1. Resolution loss: shrink then blow back up (blurs fine strokes).
    small = base.resize((int(w * 0.55), int(h * 0.55)), Image.BILINEAR)
    soft = small.resize((w, h), Image.BILINEAR)

    # 2. Skew: a few degrees of rotation, white paper background.
    rot = soft.rotate(-3.5, expand=True, fillcolor=(255, 255, 255), resample=Image.BILINEAR)

    # 3. Sensor noise: blend a speckle layer over the page.
    noise = Image.effect_noise(rot.size, 30).convert("RGB")
    noisy = Image.blend(rot, noise, 0.18)

    # 4. Soft focus.
    out = noisy.filter(ImageFilter.GaussianBlur(0.7))
    out.save(dst)
    print(f"wrote {dst} ({out.size[0]}x{out.size[1]})")


if __name__ == "__main__":
    _degrade(_SRC, _DST)
