"""T59a acceptance tests (LOCKED) — Week-2 dashboard panel aggregation.

The Week-2 dashboard panels (W2_ARCHITECTURE.md §7) are DERIVED from the T57
structured events, not new infra. `panels.aggregate_week2_events(events)` folds a
stream of event records (the dicts `events.log_event` emits/returns) into the
panel metrics: document-ingestion count, extraction field-level pass rate, RAG
retrieval hit rate, and supervisor routing-decision counts.

The event records are built via the REAL `events.log_event` so the panel reads the
actual emitted field names (`event`, `outcome`, `count`, `from_`, `to`) — a
producer/consumer contract (decision #12), not a hand-rolled fake shape.

Deterministic: pure aggregation over in-memory records; no network.
"""
import pytest

from events import (
    EVAL_RUN,
    EXTRACTION_FIELD,
    INGESTION_COMPLETE,
    INGESTION_START,
    RETRIEVAL_HIT,
    RETRIEVAL_MISS,
    WORKER_HANDOFF,
    log_event,
)
from panels import aggregate_week2_events


def _stream():
    """A representative Week-2 event stream, built via the real emitter."""
    cid = "corr-1"
    return [
        log_event(INGESTION_START, cid, document_id=5, doc_type="lab_pdf"),
        log_event(INGESTION_COMPLETE, cid, document_id=5, doc_type="lab_pdf"),
        log_event(INGESTION_COMPLETE, cid, document_id=6, doc_type="intake_form"),
        log_event(EXTRACTION_FIELD, cid, field="a", outcome="ok"),
        log_event(EXTRACTION_FIELD, cid, field="b", outcome="ok"),
        log_event(EXTRACTION_FIELD, cid, field="c", outcome="ok"),
        log_event(EXTRACTION_FIELD, cid, field="d", outcome="unsupported"),
        log_event(RETRIEVAL_HIT, cid, count=3),
        log_event(RETRIEVAL_HIT, cid, count=2),
        log_event(RETRIEVAL_MISS, cid),
        log_event(WORKER_HANDOFF, cid, from_="supervisor", to="evidence_retriever"),
        log_event(WORKER_HANDOFF, cid, from_="evidence_retriever", to="supervisor"),
        log_event(WORKER_HANDOFF, cid, from_="supervisor", to="intake_extractor"),
        log_event(EVAL_RUN, cid, passed=5, total=5),  # not a panel here -> ignored
    ]


def test_ingestion_count_is_completed_documents():
    agg = aggregate_week2_events(_stream())
    assert agg["ingestion_count"] == 2  # two ingestion.complete (start not counted)


def test_extraction_field_pass_rate_and_outcome_counts():
    agg = aggregate_week2_events(_stream())
    ex = agg["extraction"]
    assert ex["total"] == 4
    assert ex["ok"] == 3
    assert ex["field_pass_rate"] == pytest.approx(0.75)
    assert ex["by_outcome"]["ok"] == 3
    assert ex["by_outcome"]["unsupported"] == 1


def test_retrieval_hit_rate():
    agg = aggregate_week2_events(_stream())
    r = agg["retrieval"]
    assert r["hits"] == 2
    assert r["misses"] == 1
    assert r["hit_rate"] == pytest.approx(2 / 3)


def test_routing_decisions_counted_by_target():
    agg = aggregate_week2_events(_stream())
    assert agg["routing"] == {
        "evidence_retriever": 1,
        "supervisor": 1,
        "intake_extractor": 1,
    }


def test_unknown_or_unrelated_events_are_ignored_not_errors():
    # An event type outside the panel set must not raise or corrupt the counts.
    stream = _stream() + [{"event": "some.other.thing", "correlation_id": "x"}]
    agg = aggregate_week2_events(stream)
    assert agg["ingestion_count"] == 2  # unchanged


def test_empty_stream_is_zero_with_defined_rates():
    agg = aggregate_week2_events([])
    assert agg["ingestion_count"] == 0
    assert agg["extraction"]["total"] == 0
    assert agg["extraction"]["field_pass_rate"] == 0.0     # no divide-by-zero
    assert agg["retrieval"]["hits"] == 0
    assert agg["retrieval"]["hit_rate"] == 0.0             # no divide-by-zero
    assert agg["routing"] == {}


def test_output_is_json_serializable():
    import json
    json.dumps(aggregate_week2_events(_stream()))
