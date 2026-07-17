"""T58a acceptance tests (LOCKED) — resilience primitives.

The sidecar's remote dependency calls (Qdrant in T58b, and any network backend)
need to fail fast when a downstream is out rather than hammer a dead service.
`sidecar/resilience.py` provides a `CircuitBreaker`
(closed → open after N consecutive failures → half-open after a cooldown →
closed on a probe success / re-open on a probe failure) and a `call_resilient`
helper enforcing a per-call timeout, bounded retries, and breaker consultation.

Deterministic: time is injected via a fake `clock` (and a no-op/recording
`sleep`); no wall-clock, no threads, no sockets.
"""
import pytest

from resilience import (
    CircuitBreaker,
    CircuitOpenError,
    call_resilient,
)


class FakeClock:
    """A deterministic, manually-advanced monotonic clock."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _noop_sleep(_seconds: float) -> None:
    return None


# --- CircuitBreaker lifecycle -------------------------------------------------

def test_breaker_starts_closed_and_allows():
    br = CircuitBreaker(fail_max=3, reset_timeout=30, clock=FakeClock())
    assert br.state == "closed"
    assert br.allow() is True


def test_breaker_opens_after_fail_max_consecutive_failures():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=3, reset_timeout=30, clock=clock)
    br.record_failure()
    br.record_failure()
    assert br.state == "closed"          # 2 < 3, still closed
    assert br.allow() is True
    br.record_failure()                   # 3rd consecutive failure
    assert br.state == "open"
    assert br.allow() is False


def test_open_breaker_transitions_to_half_open_after_reset_timeout():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=1, reset_timeout=30, clock=clock)
    br.record_failure()                   # opens at t=0
    assert br.allow() is False
    clock.advance(29)
    assert br.allow() is False            # cooldown not yet elapsed
    assert br.state == "open"
    clock.advance(1)                      # t=30 == reset_timeout
    assert br.allow() is True             # half-open: one probe allowed
    assert br.state == "half_open"


def test_success_in_half_open_closes_the_breaker():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=1, reset_timeout=30, clock=clock)
    br.record_failure()
    clock.advance(30)
    assert br.allow() is True             # half-open
    br.record_success()
    assert br.state == "closed"
    assert br.allow() is True


def test_failure_in_half_open_reopens_and_restarts_cooldown():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=1, reset_timeout=30, clock=clock)
    br.record_failure()                   # open at t=0
    clock.advance(30)
    assert br.allow() is True             # half-open at t=30
    br.record_failure()                   # probe failed -> reopen at t=30
    assert br.state == "open"
    assert br.allow() is False
    clock.advance(29)
    assert br.allow() is False            # new cooldown measured from t=30
    clock.advance(1)                      # t=60
    assert br.allow() is True             # half-open again


def test_success_resets_the_consecutive_failure_count():
    br = CircuitBreaker(fail_max=3, reset_timeout=30, clock=FakeClock())
    br.record_failure()
    br.record_failure()                   # 2 consecutive
    br.record_success()                   # resets the count
    br.record_failure()
    br.record_failure()                   # only 2 again -> still closed
    assert br.state == "closed"


def test_breaker_public_methods_never_raise():
    br = CircuitBreaker(fail_max=1, reset_timeout=5, clock=FakeClock())
    # exercised across states; none of these should throw
    assert br.allow() in (True, False)
    br.record_failure()
    assert br.allow() in (True, False)
    br.record_success()
    assert br.state in ("closed", "open", "half_open")


# --- call_resilient: success / retry paths ------------------------------------

def test_call_resilient_returns_result_on_success():
    clock = FakeClock()
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "value"

    assert call_resilient(fn, timeout=10, retries=3, clock=clock, sleep=_noop_sleep) == "value"
    assert calls["n"] == 1                 # no retries needed


def test_call_resilient_retries_then_succeeds():
    clock = FakeClock()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    result = call_resilient(flaky, timeout=10, retries=3, clock=clock, sleep=_noop_sleep)
    assert result == "ok"
    assert calls["n"] == 3                 # attempts: fail, fail, success


def test_call_resilient_reraises_after_exhausting_retries():
    clock = FakeClock()
    calls = {"n": 0}

    def always():
        calls["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        call_resilient(always, timeout=10, retries=2, clock=clock, sleep=_noop_sleep)
    assert calls["n"] == 3                 # retries + 1 total attempts


def test_call_resilient_sleeps_between_retries_only():
    clock = FakeClock()
    sleeps = []

    def always():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        call_resilient(always, timeout=10, retries=2, clock=clock, sleep=sleeps.append)
    # 3 attempts -> a sleep before each of the 2 retries, none after the last.
    assert len(sleeps) == 2


# --- call_resilient: breaker integration --------------------------------------

def test_open_breaker_short_circuits_without_calling_fn():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=1, reset_timeout=30, clock=clock)
    br.record_failure()                    # breaker is now open
    assert br.allow() is False
    called = {"n": 0}

    def fn():
        called["n"] += 1
        return "should-not-run"

    with pytest.raises(CircuitOpenError):
        call_resilient(fn, timeout=10, retries=3, breaker=br, clock=clock, sleep=_noop_sleep)
    assert called["n"] == 0                 # fail fast: fn never invoked


def test_failures_are_recorded_on_the_breaker():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=3, reset_timeout=30, clock=clock)

    def always():
        raise ValueError("boom")

    # One call with 2 retries = 3 failed attempts = 3 breaker failures -> opens.
    with pytest.raises(ValueError):
        call_resilient(always, timeout=10, retries=2, breaker=br, clock=clock, sleep=_noop_sleep)
    assert br.state == "open"


def test_success_records_success_on_the_breaker():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=2, reset_timeout=30, clock=clock)
    br.record_failure()                     # 1 failure, still closed

    def fn():
        return "ok"

    assert call_resilient(fn, timeout=10, retries=0, breaker=br, clock=clock, sleep=_noop_sleep) == "ok"
    # the success reset the failure count: a single further failure must not open it
    br.record_failure()
    assert br.state == "closed"


# --- call_resilient: timeout --------------------------------------------------

def test_call_exceeding_timeout_is_treated_as_a_failed_attempt():
    clock = FakeClock(0)

    def slow():
        clock.advance(5)                    # cooperative: advances past the timeout
        return "too-late"

    with pytest.raises(TimeoutError):
        call_resilient(slow, timeout=1, retries=0, clock=clock, sleep=_noop_sleep)


def test_timeout_counts_toward_retries_and_breaker_failures():
    clock = FakeClock(0)
    br = CircuitBreaker(fail_max=2, reset_timeout=30, clock=clock)
    calls = {"n": 0}

    def slow():
        calls["n"] += 1
        clock.advance(5)                    # every attempt overruns the 1s budget
        return "late"

    with pytest.raises(TimeoutError):
        call_resilient(slow, timeout=1, retries=1, breaker=br, clock=clock, sleep=_noop_sleep)
    assert calls["n"] == 2                   # retried once
    assert br.state == "open"                # 2 timeouts == fail_max
