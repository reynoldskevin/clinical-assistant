"""Week-2 PHI-free structured log events.

`W2_ARCHITECTURE.md` §7 defines a small closed set of structured events that make
a Week-2 request reconstructable from the log alone, joined by ``correlation_id``.
Every event is emitted as one JSON object on the dedicated ``sidecar.events``
logger at INFO. The events are PHI-free BY CONTRACT: callers pass only ids,
outcomes, and counts — never extracted values or identifiers.

Pure stdlib (``json`` + ``logging`` only): no dependencies, no network.
"""
from __future__ import annotations

import json
import logging

# The seven Week-2 event types, searchable by correlation id.
INGESTION_START = "ingestion.start"
INGESTION_COMPLETE = "ingestion.complete"
EXTRACTION_FIELD = "extraction.field"
RETRIEVAL_HIT = "retrieval.hit"
RETRIEVAL_MISS = "retrieval.miss"
WORKER_HANDOFF = "worker.handoff"
EVAL_RUN = "eval.run"

# The closed set of declared event types. ``log_event`` rejects anything else.
WEEK2_EVENTS = {
    INGESTION_START,
    INGESTION_COMPLETE,
    EXTRACTION_FIELD,
    RETRIEVAL_HIT,
    RETRIEVAL_MISS,
    WORKER_HANDOFF,
    EVAL_RUN,
}

_LOGGER = logging.getLogger("sidecar.events")


def log_event(event: str, correlation_id: str, **fields: object) -> dict:
    """Emit one PHI-free structured event as JSON and return the record.

    Raises ``ValueError`` if ``event`` is not one of the declared
    :data:`WEEK2_EVENTS`. The record is ``{"event", "correlation_id", **fields}``;
    callers supply only ids/outcomes/counts to keep it identifier-free.
    """
    if event not in WEEK2_EVENTS:
        raise ValueError(f"unknown event type: {event!r}")
    record = {"event": event, "correlation_id": correlation_id, **fields}
    _LOGGER.info(json.dumps(record))
    return record
