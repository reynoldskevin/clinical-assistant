"""Production wiring for the sidecar: real Anthropic message-creator + HTTP boundary.

Kept separate from ``agent.py`` so the agent itself stays SDK-free and
unit-testable. This module is the only place the anthropic SDK and network I/O
live. Both builders are dependency-injectable (``client`` / ``opener``) so they
can be exercised in tests without a live API call or a running OpenEMR.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Callable


def build_message_creator(
    api_key: str | None = None,
    *,
    client: Any = None,
    model: str = "claude-opus-4-8",
) -> Callable[..., Any]:
    """Return a message-creator backed by the Anthropic SDK.

    The returned callable matches the signature ``ClaudeAgent`` expects
    (``model=``, ``max_tokens=``, ``system=``, ``tools=``, ``messages=``) and
    returns the SDK ``Message`` object unchanged (``.content`` / ``.usage`` /
    ``.stop_reason``). The anthropic SDK is imported lazily so importing this
    module — or the agent — never requires the SDK to be installed.
    """
    if client is None:
        import anthropic  # lazy: only needed when actually talking to the API

        client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
        )

        # Optional Braintrust observability: when a key is configured, wrap the
        # client so every Claude call is auto-logged (inputs, outputs, tokens,
        # cost, latency). Guarded so observability can never break the agent path.
        if os.environ.get("BRAINTRUST_API_KEY"):
            try:
                from braintrust import init_logger, wrap_anthropic

                init_logger(project=os.environ.get("BRAINTRUST_PROJECT", "oe-ai-agent"))
                client = wrap_anthropic(client)
            except Exception:  # noqa: BLE001 - never let telemetry wiring fail the request path
                logging.getLogger("sidecar").exception("Braintrust init failed; continuing without it")

    def create(**kwargs: Any) -> Any:
        kwargs.setdefault("model", model)
        return client.messages.create(**kwargs)

    return create


def build_boundary(
    summary_url: str,
    jwt: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 15.0,
) -> Callable[[int], dict[str, Any]]:
    """Return a boundary callable that fetches the patient summary over HTTP.

    The scoped JWT is forwarded as a Bearer token; the OpenEMR boundary verifies
    it (pid scope, audience, expiry) before returning any chart data. A non-2xx
    response makes ``opener`` raise, which the agent surfaces to the model as a
    tool error rather than crashing the loop.
    """

    def boundary(pid: int) -> dict[str, Any]:
        payload = json.dumps({"pid": pid}).encode("utf-8")
        request = urllib.request.Request(
            summary_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt}",
            },
        )
        with opener(request, timeout=timeout) as response:
            body = response.read()

        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("boundary returned a non-object summary")
        return parsed

    return boundary
