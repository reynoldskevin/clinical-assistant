"""T73 acceptance tests (LOCKED) — the bounded in-memory event buffer.

`/metrics` renders the Week-2 panels from recent `sidecar.events` records. This
buffer is the source: a bounded `deque`-backed `EventBuffer` fed by an
`EventBufferHandler` attached to the `sidecar.events` logger. It must evict
oldest past `maxlen`, hand out isolated snapshots, ignore non-JSON log lines, and
— via `install_event_buffer` — capture the REAL `events.log_event` emissions.

Deterministic: pure in-memory logging; no network.
"""
import json
import logging

from events import INGESTION_COMPLETE, log_event
from metrics_buffer import EventBuffer, EventBufferHandler, install_event_buffer


def test_buffer_evicts_oldest_past_maxlen():
    b = EventBuffer(maxlen=3)
    for i in range(5):
        b.add({"event": "e", "i": i})
    snap = b.snapshot()
    assert [r["i"] for r in snap] == [2, 3, 4]   # only the last 3 retained
    assert b.maxlen == 3


def test_len_reflects_contents():
    b = EventBuffer(maxlen=10)
    assert len(b) == 0
    b.add({"event": "e"})
    b.add({"event": "e"})
    assert len(b) == 2


def test_snapshot_is_isolated():
    b = EventBuffer(maxlen=10)
    b.add({"event": "e", "i": 0})
    snap = b.snapshot()
    snap.append({"event": "injected"})   # mutating the returned list...
    b.add({"event": "e", "i": 1})         # ...and adding to the buffer afterwards
    assert len(b) == 2                    # buffer is unaffected by snapshot mutation
    assert len(snap) == 2                 # and the earlier snapshot did not grow


def test_handler_parses_json_records_into_the_buffer():
    b = EventBuffer(maxlen=10)
    logger = logging.getLogger("test.metrics.json")
    logger.handlers = []
    logger.addHandler(EventBufferHandler(b))
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info(json.dumps({"event": "retrieval.hit", "count": 3}))
    snap = b.snapshot()
    assert snap[-1]["event"] == "retrieval.hit"
    assert snap[-1]["count"] == 3


def test_handler_ignores_non_json_records_without_raising():
    b = EventBuffer(maxlen=10)
    logger = logging.getLogger("test.metrics.nonjson")
    logger.handlers = []
    logger.addHandler(EventBufferHandler(b))
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("this is not json")       # must be swallowed, not raise
    logger.info("%s partial", "still not json")
    assert len(b) == 0


def test_install_event_buffer_captures_real_log_event_emissions():
    # Contract (decision #12): the REAL events.log_event producer feeds the buffer
    # the /metrics consumer reads — not a hand-rolled record shape.
    buf = install_event_buffer(maxlen=50)
    log_event(INGESTION_COMPLETE, "cid-xyz", document_id=7, doc_type="lab_pdf")
    events = buf.snapshot()
    assert any(
        r.get("event") == INGESTION_COMPLETE and r.get("correlation_id") == "cid-xyz"
        for r in events
    )


def test_install_event_buffer_does_not_stack_handlers():
    logger = logging.getLogger("sidecar.events")
    install_event_buffer(maxlen=10)
    before = sum(isinstance(h, EventBufferHandler) for h in logger.handlers)
    install_event_buffer(maxlen=10)
    after = sum(isinstance(h, EventBufferHandler) for h in logger.handlers)
    # repeated installs replace, not stack
    assert after == before == 1
