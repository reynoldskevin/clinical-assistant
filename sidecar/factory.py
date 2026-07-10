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


class ChartBoundary:
    """Operation-dispatched HTTP chart boundary.

    Each method POSTs ``{op, pid, params}`` to read.php with the forwarded Bearer
    JWT; the OpenEMR boundary verifies it (pid scope, audience, expiry) before
    returning any chart data. A non-2xx response makes ``opener`` raise, which
    the agent surfaces to the model as a tool error rather than crashing the loop.
    """

    def __init__(
        self,
        base_url: str,
        jwt: str,
        *,
        opener: Callable[..., Any],
        timeout: float,
    ) -> None:
        self._base_url = base_url
        self._jwt = jwt
        self._opener = opener
        self._timeout = timeout

    def _post(self, op: str, pid: int, params: dict[str, Any]) -> dict[str, Any] | list[Any]:
        payload = json.dumps({"op": op, "pid": pid, "params": params}).encode("utf-8")
        request = urllib.request.Request(
            self._base_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._jwt}",
            },
        )
        with self._opener(request, timeout=self._timeout) as response:
            body = response.read()

        parsed = json.loads(body)
        # read.php returns the provider result directly: an object for summary /
        # get_encounter, and a bare ARRAY for list_encounters / get_results. Accept
        # both — a JSON scalar (string/number/null) would be the unexpected case.
        if not isinstance(parsed, (dict, list)):
            raise ValueError("chart boundary returned an unexpected result type")
        return parsed

    def summary(self, pid: int) -> dict[str, Any]:
        result = self._post("summary", pid, {})
        if not isinstance(result, dict):
            raise ValueError("summary result must be an object")
        return result

    def list_encounters(self, pid: int) -> list[Any]:
        result = self._post("list_encounters", pid, {})
        if not isinstance(result, list):
            raise ValueError("list_encounters result must be an array")
        return result

    def get_encounter(self, pid: int, encounter_id: int) -> dict[str, Any]:
        result = self._post("get_encounter", pid, {"encounter_id": encounter_id})
        if not isinstance(result, dict):
            raise ValueError("get_encounter result must be an object")
        return result

    def get_results(self, pid: int) -> dict[str, Any]:
        return self._post("get_results", pid, {})


def build_chart_boundary(
    base_url: str,
    jwt: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 15.0,
) -> ChartBoundary:
    """Return an operation-dispatched chart boundary bound to ``base_url``/``jwt``.

    Exposes ``.summary(pid)`` / ``.list_encounters(pid)`` /
    ``.get_encounter(pid, encounter_id)``, each POSTing the matching ``op`` to
    read.php with the forwarded Bearer JWT.
    """
    return ChartBoundary(base_url, jwt, opener=opener, timeout=timeout)


def build_encounter_tools(chart_boundary: ChartBoundary) -> list[dict[str, Any]]:
    """Turn a chart boundary into the encounter-navigation ToolSpecs.

    Each spec is ``{name, description, input_schema, handler(pid, tool_input)}``.
    The handlers dispatch to the boundary with the session pid; get_encounter
    additionally requires a model-supplied ``encounter_id``.
    """
    return [
        {
            "name": "list_encounters",
            "description": (
                "List the current patient's encounters (visits), most recent "
                "first, with each encounter's id, date, and reason. Takes no "
                "arguments: the patient is fixed for this session."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "handler": lambda pid, inp: chart_boundary.list_encounters(pid),
        },
        {
            "name": "get_encounter",
            "description": (
                "Retrieve the detail of a single encounter (visit) for the "
                "current patient by its encounter id. Use list_encounters first "
                "to find the id."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"encounter_id": {"type": "integer"}},
                "required": ["encounter_id"],
                "additionalProperties": False,
            },
            "handler": lambda pid, inp: chart_boundary.get_encounter(pid, int(inp["encounter_id"])),
        },
    ]


def build_results_tool(chart_boundary: ChartBoundary) -> dict[str, Any]:
    """Turn a chart boundary into the lab/diagnostic-results ToolSpec.

    A single ``{name, description, input_schema, handler(pid, tool_input)}`` dict.
    The handler dispatches to the boundary with the fixed session pid; the model
    supplies no arguments (the patient is fixed for this session).
    """
    return {
        "name": "get_results",
        "description": (
            "Retrieve the current patient's lab and diagnostic results — each "
            "result's value, units, reference range, abnormal flag, status, and "
            "date. A complete results view, distinct from the summary's capped "
            "recent labs. Takes no arguments: the patient is fixed for this "
            "session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "handler": lambda pid, inp: chart_boundary.get_results(pid),
    }
