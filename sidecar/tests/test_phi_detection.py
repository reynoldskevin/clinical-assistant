"""T61 acceptance tests (LOCKED) — PHI-detection CI check.

`W2_ARCHITECTURE.md` §11 promises: "A PHI-detection check ... fails the build if
identifier or value patterns (SSN/MRN/name/DOB, lab-value shapes) appear in Week 2
log/trace output." This ticket makes that real:

  * `sidecar/phi_scan.py` — a deterministic detector. ``find_phi`` flags every PHI
    shape (ssn / mrn / dob / phone / lab_value); ``find_identifiers`` flags only
    the DIRECT patient identifiers (ssn / mrn / dob / phone) — clinical value
    shapes are deliberately excluded there because public guideline text (which
    legitimately rides along in a trace's retrieval hits) contains value shapes
    like "< 7 %", and flagging those would be a false positive.
  * an EMISSION GUARD — exercise the real Week-2 log/trace emission points and
    assert no direct identifier ever appears in what the sidecar emits.
  * a `security:phi` GitLab job — a dedicated blocking, offline, no-secrets gate,
    mirroring the T66 `security:deps` / `security:scan` jobs.

Deterministic: no live API, no sockets — scripted agent fakes, captured logs, and
static `.gitlab-ci.yml` parsing only.
"""
import json
import logging
import os
from types import SimpleNamespace

import yaml

from agent import ClaudeAgent
from observability import TraceCollector
from phi_scan import find_identifiers, find_phi
from server import process_ask

_HERE = os.path.dirname(__file__)
GITLAB_CI = os.path.join(_HERE, "..", "..", ".gitlab-ci.yml")


# --- 1. the detector catches every PHI shape ---------------------------------

def test_find_phi_detects_ssn():
    assert any(m["kind"] == "ssn" for m in find_phi("patient 123-45-6789 admitted"))


def test_find_phi_detects_dob():
    assert any(m["kind"] == "dob" for m in find_phi("DOB 1925-06-24 on file"))


def test_find_phi_detects_mrn():
    assert any(m["kind"] == "mrn" for m in find_phi("chart MRN: 00847213 pulled"))


def test_find_phi_detects_phone():
    assert any(m["kind"] == "phone" for m in find_phi("call the patient at 415-555-0132"))


def test_find_phi_detects_lab_value():
    assert any(m["kind"] == "lab_value" for m in find_phi("HbA1c came back 7.4 mg/dL today"))


def test_find_phi_is_clean_on_phifree_outcome_events():
    # The Week-2 structured events carry field names + outcomes, never values.
    event = '{"event":"extraction.field","field":"hba1c","outcome":"ok"}'
    assert find_phi(event) == []


# --- 2. find_identifiers excludes clinical value shapes ----------------------

def test_find_identifiers_flags_direct_identifiers():
    assert any(m["kind"] == "ssn" for m in find_identifiers("ssn 123-45-6789"))
    assert any(m["kind"] == "dob" for m in find_identifiers("dob 1925-06-24"))


def test_find_identifiers_ignores_guideline_value_shapes():
    # A guideline snippet legitimately carries value shapes; it is NOT an identifier.
    assert find_identifiers("target HbA1c < 7 % per ADA 2024 (glucose 5.6 mmol/L)") == []


# --- 3. emission guard: real log/trace output carries no identifiers ----------

def _agent_builder(pid, jwt):
    # The chart data the agent reads contains synthetic identifiers; the sidecar
    # must never let them reach its emitted log/trace stream.
    return ClaudeAgent(
        lambda **k: SimpleNamespace(
            content=[SimpleNamespace(type="text", text="A grounded answer.")],
            stop_reason="end_turn",
        ),
        lambda p: {"ssn": "123-45-6789", "dob": "1925-06-24", "phone": "415-555-0132"},
        correlation_id="cid-phi",
    )


def test_ask_trace_log_line_carries_no_identifiers(caplog):
    with caplog.at_level(logging.INFO, logger="sidecar"):
        status, _ = process_ask(
            "Bearer jwt",
            json.dumps({"pid": 42, "question": "summarize the chart"}).encode(),
            _agent_builder,
        )
    assert status == 200
    # The per-turn "agent turn: … trace=…" line (and everything else emitted) is
    # free of direct patient identifiers.
    found = find_identifiers(caplog.text)
    assert found == [], f"identifiers leaked into logs: {found}\n{caplog.text}"


def test_serialized_trace_summary_carries_no_identifiers():
    tc = TraceCollector()
    tc.record_model_response(1200, 240)
    tc.record_tool_call("get_medications", True)
    tc.record_verification("pass")
    # A retrieval hit carries guideline text with value shapes — allowed; the
    # serialized summary must still contain no direct patient identifiers.
    tc.record_retrieval([{"ref": "[S1]", "score": 0.91, "snippet": "target HbA1c < 7 % (ADA 2024)"}])
    blob = json.dumps(tc.summary())
    assert find_identifiers(blob) == [], blob


# --- 4. the PHI check is wired as a blocking, offline CI job ------------------

def _pipeline() -> dict:
    with open(GITLAB_CI) as fh:
        return yaml.safe_load(fh.read())


def _all_script(job: dict) -> str:
    parts = list(job.get("before_script", []) or []) + list(job.get("script", []) or [])
    return " ".join(parts)


def test_security_phi_job_is_declared_in_the_security_stage():
    data = _pipeline()
    assert "security" in data.get("stages", []), f"stages missing 'security': {data.get('stages')}"
    assert "security:phi" in data, "no security:phi job declared"
    assert data["security:phi"].get("stage") == "security"


def test_security_phi_job_runs_the_phi_guard_offline():
    job = _pipeline()["security:phi"]
    blob = _all_script(job)
    assert "pytest" in blob, "security:phi should run the offline pytest guard"
    assert "test_phi_detection" in blob, "security:phi should run the PHI-detection guard"
    # Offline / no secrets: the job must not depend on live-eval secrets.
    assert "--live" not in blob
