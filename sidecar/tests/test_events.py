"""T57a acceptance tests (LOCKED) — Week-2 structured log events.

`W2_ARCHITECTURE.md` §7 defines a set of PHI-free structured events, searchable by
`correlation_id`, that make a Week-2 request reconstructable from the log alone.
This ticket adds the event spine (`sidecar/events.py`) and wires the emission
points that already carry a correlation id:

  * `worker.handoff`                — every supervisor↔worker hop in the graph.
  * `retrieval.hit` / `retrieval.miss` — the evidence worker, by citation count.
  * `extraction.field`              — the intake worker, one per field OUTCOME
                                      (ok / unsupported / low_confidence), never
                                      the extracted value.
  * `ingestion.start` / `ingestion.complete` — bracketing `/extract`.
  * `eval.run`                      — one per eval sweep (`run_all`).

Events are emitted as JSON on the dedicated ``sidecar.events`` logger. The tests
are deterministic — scripted graph tools, a monkeypatched extractor, and a tiny
temp eval dir; no live API, no sockets. The PHI-free guarantee is checked with
the T61 ``phi_scan`` detector.
"""
import json
import logging

import pytest

import server
from events import (
    EVAL_RUN,
    EXTRACTION_FIELD,
    INGESTION_COMPLETE,
    INGESTION_START,
    RETRIEVAL_HIT,
    RETRIEVAL_MISS,
    WEEK2_EVENTS,
    WORKER_HANDOFF,
    log_event,
)
from graph import _EVIDENCE, _INTAKE, build_supervisor_graph
from phi_scan import find_identifiers

EVENTS_LOGGER = "sidecar.events"


# --- helpers -----------------------------------------------------------------

def _events(caplog, kind=None):
    out = []
    for rec in caplog.records:
        if rec.name != EVENTS_LOGGER:
            continue
        try:
            payload = json.loads(rec.getMessage())
        except (ValueError, TypeError):
            continue
        if kind is None or payload.get("event") == kind:
            out.append(payload)
    return out


class _Tool:
    """A scripted graph leaf tool: returns fixed citations + payload."""

    def __init__(self, citations, payload=None):
        self._citations = list(citations)
        self._payload = dict(payload or {})

    def __call__(self, *, question, pid, correlation_id):
        return {"citations": list(self._citations), "payload": dict(self._payload)}


def _invoke(*, route, extractor, retriever, cid="cid-graph"):
    app = build_supervisor_graph(
        extractor=extractor,
        retriever=retriever,
        finalizer=lambda state: "composed-answer",
    )
    return app.invoke({"question": "anything", "pid": 1, "correlation_id": cid, "route": route})


# --- 1. the event spine ------------------------------------------------------

def test_week2_event_types_are_declared():
    assert WEEK2_EVENTS == {
        "ingestion.start",
        "ingestion.complete",
        "extraction.field",
        "retrieval.hit",
        "retrieval.miss",
        "worker.handoff",
        "eval.run",
    }
    assert INGESTION_START == "ingestion.start"
    assert WORKER_HANDOFF == "worker.handoff"
    assert EVAL_RUN == "eval.run"


def test_log_event_emits_structured_record_and_returns_it(caplog):
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        rec = log_event(WORKER_HANDOFF, "cid-1", from_="supervisor", to="intake_extractor")
    assert rec["event"] == "worker.handoff"
    assert rec["correlation_id"] == "cid-1"
    emitted = _events(caplog)
    assert len(emitted) == 1
    assert emitted[0]["event"] == "worker.handoff"
    assert emitted[0]["correlation_id"] == "cid-1"
    assert emitted[0]["from_"] == "supervisor"
    assert emitted[0]["to"] == "intake_extractor"


def test_log_event_rejects_an_unknown_event_type():
    with pytest.raises(ValueError):
        log_event("bogus.event", "cid-1")


def test_emitted_events_are_phi_free(caplog):
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        log_event(EXTRACTION_FIELD, "cid-2", field="hba1c", outcome="ok")
        log_event(RETRIEVAL_HIT, "cid-2", count=3)
    assert find_identifiers(caplog.text) == [], caplog.text


# --- 2. graph handoff events -------------------------------------------------

def test_worker_handoff_event_per_hop(caplog):
    extractor = _Tool(["intake:1"], {"field_outcomes": {"hba1c": "ok"}})
    retriever = _Tool(["[S1]"])
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        state = _invoke(route=[_INTAKE, _EVIDENCE], extractor=extractor, retriever=retriever, cid="cid-hop")
    handoffs = _events(caplog, WORKER_HANDOFF)
    # One event per routing-log hop, each carrying the correlation id + from/to.
    assert len(handoffs) == len(state["routing_log"])
    assert handoffs, "no worker.handoff events emitted"
    for ev in handoffs:
        assert ev["correlation_id"] == "cid-hop"
        assert "from_" in ev and "to" in ev


# --- 3. retrieval hit / miss -------------------------------------------------

def test_retrieval_hit_when_evidence_worker_returns_citations(caplog):
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        _invoke(route=[_EVIDENCE], extractor=_Tool([]), retriever=_Tool(["[S1]", "[S2]"]), cid="cid-hit")
    hits = _events(caplog, RETRIEVAL_HIT)
    misses = _events(caplog, RETRIEVAL_MISS)
    assert len(hits) == 1 and not misses
    assert hits[0]["correlation_id"] == "cid-hit"
    assert hits[0]["count"] == 2


def test_retrieval_miss_when_evidence_worker_returns_no_citations(caplog):
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        _invoke(route=[_EVIDENCE], extractor=_Tool([]), retriever=_Tool([]), cid="cid-miss")
    assert len(_events(caplog, RETRIEVAL_MISS)) == 1
    assert not _events(caplog, RETRIEVAL_HIT)


# --- 4. extraction.field (outcomes only, never values) -----------------------

def test_extraction_field_events_carry_outcomes_not_values(caplog):
    extractor = _Tool(
        ["intake:1"],
        {"field_outcomes": {"hba1c": "ok", "allergies": "unsupported", "dob": "low_confidence"}},
    )
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        _invoke(route=[_INTAKE], extractor=extractor, retriever=_Tool([]), cid="cid-field")
    fields = _events(caplog, EXTRACTION_FIELD)
    assert {e["field"] for e in fields} == {"hba1c", "allergies", "dob"}
    assert {e["outcome"] for e in fields} == {"ok", "unsupported", "low_confidence"}
    for e in fields:
        assert e["correlation_id"] == "cid-field"
        # the record carries only field name + outcome, never an extracted value
        assert set(e) <= {"event", "correlation_id", "field", "outcome"}
    assert find_identifiers(caplog.text) == []


# --- 5. ingestion.start / ingestion.complete bracket /extract ----------------

def test_ingestion_events_bracket_the_extract_flow(caplog, monkeypatch):
    class _Fact:
        def model_dump(self):
            return {}

    fake_result = type(
        "R",
        (),
        {
            "doc_type": "lab_pdf",
            "confidence": 0.9,
            "low_confidence": False,
            "unsupported_fields": [],
            "fact": _Fact(),
        },
    )()
    monkeypatch.setattr(server, "build_chart_boundary", lambda *a, **k: object())
    monkeypatch.setattr(server, "attach_and_extract", lambda *a, **k: fake_result)

    extract = server.default_extract_builder("http://oe/summary.php", None)
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        body = extract(1, "jwt", 5, "lab_pdf")
    assert body["ok"] is True
    starts = _events(caplog, INGESTION_START)
    completes = _events(caplog, INGESTION_COMPLETE)
    assert len(starts) == 1 and len(completes) == 1
    assert starts[0]["document_id"] == 5
    assert completes[0]["document_id"] == 5
    # start precedes complete
    order = [e["event"] for e in _events(caplog) if e["event"] in (INGESTION_START, INGESTION_COMPLETE)]
    assert order == [INGESTION_START, INGESTION_COMPLETE]


# --- 6. eval.run per sweep ---------------------------------------------------

def test_eval_run_event_emitted_once_per_sweep(caplog, tmp_path):
    from eval import run_all

    (tmp_path / "mini.yaml").write_text(
        "- name: happy\n  question: q\n  pid: 42\n  graders:\n    - contains: stable\n"
    )

    def runner(question, pid):
        return ("the patient is stable", {"tool_calls": 1, "tool_failures": 0})

    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        summary = run_all(str(tmp_path), runner)

    runs = _events(caplog, EVAL_RUN)
    assert len(runs) == 1
    assert runs[0]["total"] == summary["total"]
    assert runs[0]["passed"] == summary["passed"]
    assert runs[0].get("correlation_id")
