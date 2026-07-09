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


class TraceCollector:
    """Accumulates model-usage and tool-call metrics for a single agent run."""

    def __init__(self, model: str = "claude-opus-4-8") -> None:
        self._model = model
        self._model_calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._tool_calls = 0
        self._tool_failures = 0

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
        }
