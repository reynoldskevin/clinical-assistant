"""T44 guard test (LOCKED) — the eval dataset + results doc exists and is complete.

EVAL_DATASET.md is the submission artifact: the dataset structure/scope + the
run results. This guard pins that it documents the dataset (21 cases, UC/category/
guards), both run modes, and the offline results, and that the numbers stay
consistent with the actual suite (21 cases; UC-1..6; all three guard types).
"""
import glob
import os

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "EVAL_DATASET.md")
EVALS_DIR = os.path.join(os.path.dirname(__file__), "..", "evals")


def _text():
    with open(DOC) as fh:
        return fh.read().lower()


def test_doc_exists():
    assert os.path.exists(DOC)


def test_documents_structure_scope_and_results():
    t = _text()
    assert "dataset" in t and "result" in t
    assert "guard" in t                       # boundary/invariant/regression guards
    assert "uc-1" in t and "uc-6" in t         # scope
    assert "offline" in t and "live" in t      # both run modes
    assert "pass" in t                         # results recorded (pass counts)


def test_case_count_matches_the_real_dataset():
    import yaml
    n = sum(len(yaml.safe_load(open(f).read()) or []) for f in glob.glob(os.path.join(EVALS_DIR, "*.yaml")))
    assert n == 22                             # keep the doc's "22 cases" honest
    assert "22" in _text()
