"""T52 acceptance tests (LOCKED) — PR-blocking CI gate.

Extends the Week-1 eval gate with a per-rubric REGRESSION gate over the T51
golden set, plus offline integration coverage of the full ingestion->answer
path. Everything here is deterministic and offline: no Claude, no VLM, no
network, no API key. The VLM message-creator, the chart boundary, the retriever
and the finalizer are all injected fakes; the document bytes are the real
in-repo fixtures under ``sidecar/fixtures/documents/``.

Contract exercised (the implementer builds `sidecar/ci_gate.py` to satisfy the
regression-gate half; the integration half wires the EXISTING production
`extractor.attach_and_extract` + `graph.run_supervisor` through stubs):

    ci_gate.MAX_REGRESSION: float                 # 0.05 (>5% drop fails)
    ci_gate.baseline_pass_rates() -> {rubric: rate}   # reproducible, offline, all 1.0
    ci_gate.pass_rates(summary) -> {rubric: rate}     # extract from run_golden_set summary
    ci_gate.regression_gate(current, baseline=None, thresholds=None, max_regression=0.05)
        -> {"passed": bool, "regressions": [rubric], "below_threshold": [rubric], "by_rubric": {...}}
        # passed is False iff ANY rubric drops by MORE than max_regression below
        # baseline, OR falls below its own threshold.
"""
import base64
import json
import os
from types import SimpleNamespace

import pytest
import yaml

import ci_gate
import golden_set
from extractor import attach_and_extract
from graph import WorkerResult, run_supervisor
from golden_set import RUBRICS, THRESHOLDS, build_ideal_runner, run_golden_set


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "documents")
GITLAB_CI = os.path.join(os.path.dirname(__file__), "..", "..", ".gitlab-ci.yml")


# --- fakes / fixtures ----------------------------------------------------------

def _b64_fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def _text_block(t):
    return SimpleNamespace(type="text", text=t)


class ScriptedVlm:
    """Fake VLM message-creator returning one scripted JSON envelope."""

    def __init__(self, envelope):
        self._body = envelope if isinstance(envelope, str) else json.dumps(envelope)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[_text_block(self._body)], stop_reason="end_turn")


class FakeBoundary:
    """Fake chart boundary whose get_document returns one stored document."""

    def __init__(self, mimetype, document_data):
        self._doc = {"mimetype": mimetype, "document_data": document_data}
        self.calls = []

    def get_document(self, pid, document_id):
        self.calls.append((pid, document_id))
        return dict(self._doc)


def _valid_lab_envelope():
    return {
        "confidence": 0.94,
        "unsupported_fields": [],
        "fact": {
            "test_name": "HbA1c",
            "value": "6.8",
            "unit": "%",
            "reference_range": "4.0-5.6",
            "collection_date": "2026-01-05",
            "abnormal_flag": "H",
            "source_citation": "Lab Report — HbA1c row",
        },
    }


# ==============================================================================
# Regression gate — pure, flat {rubric: pass_rate} dicts (no golden set needed)
# ==============================================================================

def test_gate_passes_when_current_matches_baseline():
    baseline = {r: 1.0 for r in RUBRICS}
    result = ci_gate.regression_gate(dict(baseline), baseline=baseline)
    assert result["passed"] is True
    assert result["regressions"] == []
    assert result["below_threshold"] == []


def test_more_than_5pct_drop_fails_even_when_still_above_threshold():
    # citation_present threshold is 0.9; a drop to 0.94 is still ABOVE threshold
    # but is a >5% regression from a 1.0 baseline, so the gate must fail on it.
    baseline = {r: 1.0 for r in RUBRICS}
    current = dict(baseline)
    current["citation_present"] = 0.94  # 0.06 drop > 0.05
    result = ci_gate.regression_gate(current, baseline=baseline)
    assert result["passed"] is False
    assert "citation_present" in result["regressions"]
    assert "citation_present" not in result["below_threshold"]


def test_exactly_5pct_drop_is_allowed():
    # A drop of exactly 0.05 is NOT "more than 5%"; still >= threshold, so pass.
    baseline = {r: 1.0 for r in RUBRICS}
    current = dict(baseline)
    current["schema_valid"] = 0.95  # exactly 0.05 drop; 0.95 >= 0.9 threshold
    result = ci_gate.regression_gate(current, baseline=baseline)
    assert result["passed"] is True
    assert result["regressions"] == []


def test_below_threshold_fails_even_without_a_5pct_regression():
    # A tiny 0.01 drop is within tolerance, but it crosses BELOW the 0.9
    # threshold, which must independently fail the gate.
    baseline = {r: 1.0 for r in RUBRICS}
    baseline["schema_valid"] = 0.90
    current = dict(baseline)
    current["schema_valid"] = 0.89  # 0.01 drop (<5%) but below 0.9 threshold
    result = ci_gate.regression_gate(current, baseline=baseline)
    assert result["passed"] is False
    assert "schema_valid" in result["below_threshold"]
    assert "schema_valid" not in result["regressions"]


def test_gate_returns_a_genuine_bool_and_names_offenders():
    baseline = {r: 1.0 for r in RUBRICS}
    current = dict(baseline)
    current["factually_consistent"] = 0.0
    result = ci_gate.regression_gate(current, baseline=baseline)
    assert result["passed"] is False
    assert result["passed"] is not None and isinstance(result["passed"], bool)
    assert "factually_consistent" in result["regressions"]


def test_max_regression_constant_is_five_percent():
    assert ci_gate.MAX_REGRESSION == 0.05


# ==============================================================================
# Baseline — reproducible, offline, covers every rubric
# ==============================================================================

def test_baseline_covers_all_rubrics_in_unit_range():
    baseline = ci_gate.baseline_pass_rates()
    assert set(baseline) == set(RUBRICS)
    for rubric, rate in baseline.items():
        assert 0.0 <= rate <= 1.0


def test_baseline_is_deterministic_across_calls():
    assert ci_gate.baseline_pass_rates() == ci_gate.baseline_pass_rates()


def test_pass_rates_extracts_per_rubric_rate_from_a_summary():
    summary = run_golden_set(build_ideal_runner())
    rates = ci_gate.pass_rates(summary)
    assert set(rates) == set(RUBRICS)
    assert all(rate == 1.0 for rate in rates.values())


# ==============================================================================
# Seeded end-to-end regression over the golden set (acceptance #1)
# ==============================================================================

def _degraded_citation_runner():
    """Wrap the ideal runner but strip the citation marker from citation cases,
    so ONLY the citation_present rubric collapses — a seeded per-category
    regression the gate must catch."""
    ideal = build_ideal_runner()

    def runner(question, pid):
        text, trace = ideal(question, pid)
        if "[rubric:citation_present]" in question:
            text = text.replace(golden_set.CITATION_MARKER, "")
            trace = {**trace, "retrieval_hits": 0}
        return text, trace

    return runner


def test_ideal_runner_passes_the_regression_gate():
    current = ci_gate.pass_rates(run_golden_set(build_ideal_runner()))
    result = ci_gate.regression_gate(current)
    assert result["passed"] is True


def test_seeded_regression_in_one_category_fails_the_gate():
    current = ci_gate.pass_rates(run_golden_set(_degraded_citation_runner()))
    result = ci_gate.regression_gate(current)
    assert result["passed"] is False
    assert "citation_present" in (result["regressions"] + result["below_threshold"])
    # The un-touched rubrics must NOT be falsely flagged.
    assert "safe_refusal" not in result["regressions"]


# ==============================================================================
# Offline ingestion -> answer integration on real fixtures + stubs (acceptance #2/#3)
# ==============================================================================

def _ingest_and_answer(monkeypatch=None):
    """Drive the REAL extractor + supervisor graph end-to-end, offline.

    VLM, chart boundary, retriever and finalizer are injected; the PDF bytes are
    the real in-repo fixture. Returns (extraction_result, final_state)."""
    boundary = FakeBoundary("application/pdf", _b64_fixture("synthetic_lab_report.pdf"))
    vlm = ScriptedVlm(_valid_lab_envelope())

    extraction = attach_and_extract(
        42, 7, "lab_pdf", chart_boundary=boundary, message_creator=vlm
    )

    fact = extraction.fact

    def extractor(*, question, pid, correlation_id):
        return {"citations": [fact.source_citation], "payload": fact.model_dump()}

    def retriever(*, question, pid, correlation_id):
        return {"citations": ["Synthetic Guideline — A1c target"], "payload": {"chunks": 1}}

    def finalizer(state):
        names = [
            wr["payload"].get("test_name")
            for wr in state["worker_results"]
            if wr.get("payload", {}).get("test_name")
        ]
        return "Extracted labs: " + ", ".join(n for n in names if n)

    state = run_supervisor(
        "Extract the uploaded lab report and summarize the result.",
        pid=42,
        extractor=extractor,
        retriever=retriever,
        finalizer=finalizer,
    )
    return extraction, state


def test_ingestion_to_answer_runs_offline_on_fixture_with_stubs(monkeypatch):
    # No API key anywhere in the environment — the whole path must still run.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    extraction, state = _ingest_and_answer()

    # Extraction flowed the fixture through the strict contract.
    assert extraction.fact.test_name == "HbA1c"
    # ...and reached the composed answer.
    assert "HbA1c" in state["answer"]


def test_extraction_schema_is_enforced_in_the_path():
    # A malformed VLM envelope (missing the required source_citation) must raise
    # through the contract — the schema is the source of truth, never bypassed.
    bad = _valid_lab_envelope()
    del bad["fact"]["source_citation"]
    boundary = FakeBoundary("application/pdf", _b64_fixture("synthetic_lab_report.pdf"))
    with pytest.raises(Exception):
        attach_and_extract(42, 7, "lab_pdf", chart_boundary=boundary, message_creator=ScriptedVlm(bad))


def test_supervisor_worker_results_satisfy_the_worker_contract():
    _extraction, state = _ingest_and_answer()
    worker_results = state["worker_results"]
    assert worker_results, "expected at least one worker result"
    for wr in worker_results:
        # Each recorded result round-trips through the strict WorkerResult model.
        WorkerResult(**wr)
        # And the strict contract rejects a smuggled unknown field.
        with pytest.raises(Exception):
            WorkerResult(**{**wr, "unexpected_field": "x"})


# ==============================================================================
# .gitlab-ci.yml wires the extended, secret-free blocking job (test plan bullet 3)
# ==============================================================================

def test_offline_gate_is_blocking_and_needs_no_secrets():
    with open(GITLAB_CI) as fh:
        raw = fh.read()
    data = yaml.safe_load(raw)

    assert "eval:offline" in data
    offline = data["eval:offline"]

    # Blocking: it must NOT be manual or allow_failure at the job level.
    rules = offline.get("rules", [])
    for rule in rules:
        assert rule.get("when") != "manual"
        assert rule.get("allow_failure") is not True
    assert offline.get("allow_failure") is not True

    # It runs the WHOLE offline test dir (which now includes the golden-set +
    # ci-gate regression/integration tests), and references no API-key secret.
    script = " ".join(offline.get("script", []))
    assert "sidecar/tests" in script
    job_blob = json.dumps(offline)
    assert "ANTHROPIC_API_KEY" not in job_blob


def test_live_sweep_still_present_and_secret_scoped():
    with open(GITLAB_CI) as fh:
        raw = fh.read()
    data = yaml.safe_load(raw)
    # The live scored sweep remains, and it is the one that carries the secret.
    assert "eval:live" in data
    assert "ANTHROPIC_API_KEY" in raw
