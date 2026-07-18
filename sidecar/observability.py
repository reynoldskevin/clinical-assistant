"""Observability spine for the sidecar Claude agent.

Provides lightweight observers that the agent notifies after every model
response and every tool call. This module imports nothing from ``agent`` (so
there is no circular import) and never touches the network.

Two observers are offered:

* :class:`NullObserver` — a no-op implementation used as the default when the
  agent is constructed without an observer.
* :class:`TraceCollector` — accumulates token usage (and derived cost) plus
  tool success/failure counts, exposed via :meth:`TraceCollector.summary`.
"""
from __future__ import annotations

import contextlib
from typing import Any

# Pricing in USD per 1,000,000 tokens as ``(input_price, output_price)``.
# Unknown models fall back to zero cost.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
}


class NullObserver:
    """An observer that records nothing (the default, zero-overhead observer)."""

    def record_model_response(self, input_tokens: int, output_tokens: int) -> None:
        """Ignore a model response's token usage."""

    def record_tool_call(self, name: str, ok: bool) -> None:
        """Ignore a tool call's outcome."""

    def record_verification(self, verdict: str) -> None:
        """Ignore the verification gate's verdict."""

    def record_truncated(self) -> None:
        """Ignore a truncated-turn signal."""

    def record_degraded(self) -> None:
        """Ignore a degraded-turn signal."""

    def record_retry(self) -> None:
        """Ignore a retry signal."""


class NullTracer:
    """A tracer that opens no spans (the default, zero-overhead tracer).

    Its :meth:`turn` returns a no-op context manager, so wrapping an agent turn
    in it has no effect. This module deliberately imports nothing from
    ``braintrust`` — the real, guarded Braintrust tracer lives in ``factory``.
    """

    def turn(self, metadata: dict[str, Any]) -> contextlib.AbstractContextManager[None]:
        """Return a no-op context manager, ignoring the turn's ``metadata``."""
        return contextlib.nullcontext()

    def worker_span(
        self,
        name: str,
        correlation_id: str,
        kind: str | None = None,
        parent: str = "supervisor",
    ) -> contextlib.AbstractContextManager[None]:
        """Return a no-op child span, ignoring all span metadata (zero overhead)."""
        return contextlib.nullcontext()

    def tool_span(self, name: str) -> contextlib.AbstractContextManager[None]:
        """Return a no-op context manager, ignoring the tool name (zero overhead)."""
        return contextlib.nullcontext()


class TraceCollector:
    """Accumulates model-usage and tool-call metrics for a single agent run."""

    def __init__(self, model: str = "claude-opus-4-8") -> None:
        self._model = model
        self._model_calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._tool_calls = 0
        self._tool_failures = 0
        self._verification_verdict: str | None = None
        self._truncated = False
        self._degraded = False
        self._retries = 0
        self._retrieval_hits: list[Any] = []

    def record_model_response(self, input_tokens: int, output_tokens: int) -> None:
        """Record one model response and accumulate its token usage."""
        self._model_calls += 1
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def record_tool_call(self, name: str, ok: bool) -> None:
        """Record one tool call, counting a failure when ``ok`` is False."""
        self._tool_calls += 1
        if not ok:
            self._tool_failures += 1

    def record_verification(self, verdict: str) -> None:
        """Record the verification gate's verdict for this turn."""
        self._verification_verdict = verdict

    def record_truncated(self) -> None:
        """Mark this turn as truncated (the tool budget was exhausted)."""
        self._truncated = True

    def record_degraded(self) -> None:
        """Mark this turn as degraded (a record lookup failed)."""
        self._degraded = True

    def record_retry(self) -> None:
        """Increment the retry counter for this turn."""
        self._retries += 1

    def record_retrieval(self, hits: Any) -> None:
        """Record the evidence-retriever's returned hits (citation + score)."""
        self._retrieval_hits.extend(hits)

    def summary(self) -> dict[str, Any]:
        """Return accumulated metrics, including the derived USD cost."""
        in_price, out_price = _PRICING.get(self._model, (0.0, 0.0))
        cost_usd = (
            self._input_tokens / 1e6 * in_price
            + self._output_tokens / 1e6 * out_price
        )
        return {
            "model_calls": self._model_calls,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "cost_usd": cost_usd,
            "tool_calls": self._tool_calls,
            "tool_failures": self._tool_failures,
            "verification_verdict": self._verification_verdict,
            "truncated": self._truncated,
            "degraded": self._degraded,
            "retries": self._retries,
            "retrieval_hits": self._retrieval_hits,
        }
