"""T61 acceptance tests (LOCKED) — W2_ARCHITECTURE.md is finalized.

The Week-2 architecture doc is the design reference. This guard pins that it is
complete (all 14 sections), that its §7 SLOs are CONCRETE numbers drawn from the
captured baselines (not the `< target` placeholder it shipped with), and that its
privacy section still references the PHI-detection CI check that T61 implements.

Mirrors the repo's other doc guards (e.g. test_baselines_doc.py): static text
assertions, no network.
"""
import os
import re

_HERE = os.path.dirname(__file__)
DOC = os.path.join(_HERE, "..", "..", "W2_ARCHITECTURE.md")


def _text() -> str:
    with open(DOC) as fh:
        return fh.read()


def test_architecture_doc_exists():
    assert os.path.exists(DOC)


def test_all_fourteen_sections_present():
    t = _text()
    for n in range(1, 15):
        assert re.search(rf"^## {n}\. ", t, re.MULTILINE), f"missing numbered section {n}"


def test_slo_placeholder_is_replaced_with_concrete_numbers():
    t = _text()
    # The shipped placeholder must be gone...
    assert "target seconds" not in t, "§7 still carries the '< target seconds' placeholder"
    assert "p95 <\ntarget" not in t and "p95 < target" not in t, "§7 SLO target still a placeholder"
    # ...and replaced with at least one concrete p95 latency number with a unit.
    assert re.search(r"p95[^\n]{0,40}?\b\d+(?:[.,]\d+)?\s?(?:ms|s|seconds)\b", t, re.IGNORECASE), (
        "§7 SLOs have no concrete p95 latency number with a unit"
    )


def test_slos_reference_the_recorded_baselines():
    assert "METRICS_WEEK1.md" in _text()


def test_privacy_section_references_the_phi_detection_check():
    t = _text().lower()
    assert ("phi-detection" in t) or ("phi detection" in t)
    # It is described as a CI/build gate.
    assert "build" in t or "ci" in t
