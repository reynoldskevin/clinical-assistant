"""Week-2 dashboard panel aggregation.

The Week-2 dashboard panels (``W2_ARCHITECTURE.md`` §7) are DERIVED from the
T57 structured events emitted by :mod:`events`, not from new infrastructure.
This module folds a stream of event records — the dicts ``events.log_event``
emits/returns, each shaped ``{"event", "correlation_id", **fields}`` — into the
panel metrics: document-ingestion count, extraction field-level pass rate, RAG
retrieval hit rate, and supervisor routing-decision counts.

The eval pass/fail-per-category panel is derived instead from an ``eval.run_all``
summary (see :func:`eval_pass_fail_by_category`).

Pure stdlib: no dependencies, no network. Aggregation is deterministic and the
output is JSON-serializable.
"""
from __future__ import annotations

from events import (
    EXTRACTION_FIELD,
    INGESTION_COMPLETE,
    RETRIEVAL_HIT,
    RETRIEVAL_MISS,
    WORKER_HANDOFF,
)


def aggregate_week2_events(events: list[dict]) -> dict:
    """Fold a stream of T57 event records into Week-2 panel metrics.

    Each record is classified by its ``event`` key. Records whose ``event`` is
    outside the panel set (including ``eval.run`` and unknown types) are ignored
    — never raise. All rates are divide-by-zero safe and the result is
    JSON-serializable.
    """
    ingestion_count = 0
    extraction_total = 0
    extraction_ok = 0
    by_outcome: dict[str, int] = {}
    hits = 0
    misses = 0
    routing: dict[str, int] = {}

    for record in events:
        event = record.get("event")

        if event == INGESTION_COMPLETE:
            ingestion_count += 1
        elif event == EXTRACTION_FIELD:
            extraction_total += 1
            outcome = record.get("outcome")
            outcome_key = str(outcome)
            by_outcome[outcome_key] = by_outcome.get(outcome_key, 0) + 1
            if outcome == "ok":
                extraction_ok += 1
        elif event == RETRIEVAL_HIT:
            hits += 1
        elif event == RETRIEVAL_MISS:
            misses += 1
        elif event == WORKER_HANDOFF:
            target = str(record.get("to"))
            routing[target] = routing.get(target, 0) + 1

    field_pass_rate = (extraction_ok / extraction_total) if extraction_total else 0.0
    hit_rate = (hits / (hits + misses)) if (hits + misses) else 0.0

    return {
        "ingestion_count": ingestion_count,
        "extraction": {
            "total": extraction_total,
            "ok": extraction_ok,
            "field_pass_rate": field_pass_rate,
            "by_outcome": by_outcome,
        },
        "retrieval": {
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate,
        },
        "routing": routing,
    }


def eval_pass_fail_by_category(summary: dict) -> dict:
    """Return the per-category pass/fail view from an ``eval.run_all`` summary.

    A thin accessor over the summary's ``by_category`` breakdown, keyed by
    category with ``{"passed", "total", "pass_rate"}`` values.
    """
    return summary["by_category"]
