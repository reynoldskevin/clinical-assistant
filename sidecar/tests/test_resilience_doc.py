"""T58c acceptance tests (LOCKED) — resilience/SLO numbers in the architecture doc.

T58a/b introduced concrete timeout/retry/circuit-breaker behaviour on the Qdrant
dependency. `W2_ARCHITECTURE.md` §7 (Observability, SLOs) must state that budget
as REAL numbers, and §10 (Failure modes) must document the fail-fast/degrade
behaviour when Qdrant is down (breaker opens → retrieval degrades, sidecar stays
live). Complements the existing T61 §7 guard (`test_architecture_doc.py`), which
must remain green.

Static text assertions, no network.
"""
import os
import re

_HERE = os.path.dirname(__file__)
DOC = os.path.join(_HERE, "..", "..", "W2_ARCHITECTURE.md")


def _norm() -> str:
    with open(DOC) as fh:
        return re.sub(r"\s+", " ", fh.read().lower())


def _has_any(text: str, options: list[str]) -> bool:
    return any(o in text for o in options)


def test_slo_section_states_the_concrete_qdrant_resilience_budget():
    n = _norm()
    assert "qdrant" in n, "the resilience budget must name the Qdrant dependency"
    assert _has_any(n, ["circuit breaker", "circuit-breaker"]), "no circuit breaker described"
    # per-call timeout (2 seconds)
    assert _has_any(n, ["2 s", "2-second", "2 second"]), "no concrete Qdrant call timeout"
    # bounded retries (2)
    assert _has_any(n, ["2 retries", "2 retr", "retries: 2"]), "no concrete retry count"
    # circuit-breaker open threshold — consecutive failures (5)
    assert "5 consecutive" in n, "no concrete circuit-breaker failure threshold"
    # reset cooldown (30 seconds)
    assert _has_any(n, ["30 s", "30-second", "30 second"]), "no concrete breaker reset cooldown"
    assert _has_any(n, ["cooldown", "reset timeout"]), "the reset window is not named"


def test_failure_modes_document_qdrant_fail_fast_and_degrade():
    n = _norm()
    # §10 (failure modes): a Qdrant outage trips the breaker and degrades retrieval
    # without taking the sidecar down.
    assert _has_any(n, ["fail fast", "fails fast", "fail-fast"]), "fail-fast behaviour not documented"
    assert "breaker" in n
    assert _has_any(n, ["degrade", "degraded", "degrades"]), "degrade behaviour not documented"
    # the sidecar/liveness survives the dependency outage
    assert _has_any(n, ["stays live", "stays up", "remains live", "still live", "liveness"]), (
        "does not state the sidecar stays live when Qdrant is down"
    )
