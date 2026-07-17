"""Deterministic resilience primitives for the sidecar's remote calls.

The sidecar's remote dependency calls (Qdrant, and any network backend) need
to fail fast when a downstream is out rather than hammer a dead service. This
module provides a :class:`CircuitBreaker` (closed → open after N consecutive
failures → half-open after a cooldown → closed on a probe success / re-open on
a probe failure) and a :func:`call_resilient` helper enforcing a per-call
cooperative timeout, bounded retries, and breaker consultation.

All time is injected via a ``clock`` callable and a ``sleep`` callable so the
logic path is deterministic and testable: no wall-clock, no threads, no
sockets. Production callers get :func:`time.monotonic` / :func:`time.sleep` as
parameter defaults.
"""
from __future__ import annotations

import time
from typing import Any, Callable


class CircuitOpenError(Exception):
    """Raised by :func:`call_resilient` when the supplied breaker is open."""


class CircuitBreaker:
    """A consecutive-failure circuit breaker with a time-based cooldown."""

    def __init__(
        self,
        fail_max: int,
        reset_timeout: float,
        clock: Callable[[], float],
    ) -> None:
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._clock = clock
        self._failures = 0
        self._state = "closed"
        self._opened_at = 0.0

    def _sync(self) -> str:
        """Apply any pending time-based open → half_open transition."""
        if self._state == "open":
            if self._clock() - self._opened_at >= self._reset_timeout:
                self._state = "half_open"
        return self._state

    @property
    def state(self) -> str:
        return self._sync()

    def allow(self) -> bool:
        state = self._sync()
        return state in ("closed", "half_open")

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        state = self._sync()
        if state == "half_open":
            # Probe failed: re-open and restart the cooldown.
            self._state = "open"
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._fail_max:
            self._state = "open"
            self._opened_at = self._clock()


def call_resilient(
    fn: Callable[[], Any],
    *,
    timeout: float | None,
    retries: int,
    breaker: CircuitBreaker | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Call ``fn`` with a cooperative timeout, bounded retries, and a breaker.

    Total attempts = ``retries + 1``. Before each attempt the breaker (if
    supplied) is consulted; an open breaker raises :class:`CircuitOpenError`
    without invoking ``fn``. A cooperative timeout (measured via ``clock``)
    turns an overrun into a :class:`TimeoutError`. Failed attempts record a
    breaker failure and retry while attempts remain; the last exception is
    re-raised when exhausted. A success records a breaker success and returns.
    """
    attempts = retries + 1
    last_exc: BaseException | None = None

    for attempt in range(attempts):
        if breaker is not None and not breaker.allow():
            raise CircuitOpenError("circuit breaker is open")

        if attempt > 0:
            sleep(_backoff_delay(attempt))

        try:
            start = clock()
            result = fn()
            elapsed = clock() - start
            if timeout is not None and elapsed > timeout:
                raise TimeoutError(
                    f"call exceeded timeout of {timeout}s (took {elapsed}s)"
                )
        except Exception as exc:  # noqa: BLE001 — retry any failure
            last_exc = exc
            if breaker is not None:
                breaker.record_failure()
            continue

        if breaker is not None:
            breaker.record_success()
        return result

    assert last_exc is not None
    raise last_exc


def _backoff_delay(attempt: int) -> float:
    """Simple exponential backoff (delay before retry number ``attempt``)."""
    return float(2 ** (attempt - 1)) * 0.1
