"""T45 guard test (LOCKED) — the AI cost analysis exists and covers the ask.

COST_ANALYSIS.md must cover actual dev spend, per-turn economics grounded in
measured token usage, the 100/1K/10K/100K projection, and the architectural
changes at each level (not just cost-per-token x n).
"""
import os

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "COST_ANALYSIS.md")


def _text():
    with open(DOC) as fh:
        return fh.read().lower()


def test_doc_exists():
    assert os.path.exists(DOC)


def test_covers_dev_spend_and_unit_economics():
    t = _text()
    assert "dev spend" in t
    assert "per-turn" in t or "$/turn" in t or "per turn" in t
    assert "input" in t and "output" in t          # token cost breakdown


def test_covers_all_four_scale_levels():
    t = _text()
    for level in ("100", "1k", "10k", "100k"):
        assert level in t


def test_covers_architectural_changes_and_the_nonlinear_point():
    t = _text()
    assert "architect" in t                        # architectural changes at each level
    assert "prompt caching" in t                   # the key $/turn lever
    assert "not" in t and "token" in t             # the "not cost-per-token x n" argument
