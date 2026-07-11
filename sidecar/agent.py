"""Sidecar Claude agent implementing a manual tool-use loop.

The Claude message-creator and the clinical boundary caller are injected as
plain callables (constructor DI), so this module never imports the anthropic
SDK and never makes a live API call. Response objects are duck-typed to the
SDK Message shape: a ``.content`` list of blocks plus a ``.stop_reason``.

The single exposed tool, ``get_patient_summary``, deliberately takes no
patient argument: the patient is fixed for the session, and the model must
not be able to redirect the lookup to a different chart.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from observability import NullObserver

# The response object returned by the message-creator (SDK Message shape).
MessageResponse = Any

# Callable signature: message_creator(model=, max_tokens=, system=, tools=, messages=).
MessageCreator = Callable[..., MessageResponse]

# Callable signature: boundary(pid) -> dict (the patient summary).
Boundary = Callable[[int], dict[str, Any]]

# An extra tool spec: {name, description, input_schema, handler}, where
# handler(pid, tool_input) -> dict. The session pid is fixed (from the token);
# the model's tool_input is passed through but can never redirect the pid.
ToolSpec = dict[str, Any]

# Default per-turn budget on the total number of tool executions. This bounds a
# runaway chain independently of (and more strictly than) the raw iteration cap.
_DEFAULT_MAX_TOOL_CALLS = 8

_SYSTEM_PROMPT = (
    "You are a clinical assistant embedded in an electronic health record. "
    "Answer questions about the current patient concisely and accurately, "
    "using the get_patient_summary tool to retrieve the patient's chart when "
    "clinical detail is needed. Never speculate beyond the retrieved data."
)


class ClaudeAgent:
    """Runs a bounded, manual tool-use loop against an injected message-creator."""

    def __init__(
        self,
        message_creator: MessageCreator,
        boundary: Boundary,
        model: str = "claude-opus-4-8",
        max_tokens: int = 4096,
        observer: Any = None,
        extra_tools: list[ToolSpec] | None = None,
        max_tool_calls: int = _DEFAULT_MAX_TOOL_CALLS,
    ) -> None:
        self._message_creator = message_creator
        self._boundary = boundary
        self._model = model
        self._max_tokens = max_tokens
        self._observer = observer or NullObserver()
        # Injectable tool registry keyed by name, each carrying its handler.
        self._extra_tools = list(extra_tools or [])
        # Cap on the total number of tool executions per turn. Once this many
        # tools have run, the loop stops offering tools and forces a final
        # text answer from whatever the model has already gathered.
        self._max_tool_calls = max_tool_calls

    @property
    def observer(self) -> Any:
        """The observability collector for this run (token usage, cost, tool calls)."""
        return self._observer

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_patient_summary",
                "description": (
                    "Retrieve a structured clinical summary of the current "
                    "patient, including demographics, active problems, "
                    "medications, allergies, and recent vitals. Takes no "
                    "arguments: the patient is fixed for this session."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            *(
                {
                    "name": spec["name"],
                    "description": spec["description"],
                    "input_schema": spec["input_schema"],
                }
                for spec in self._extra_tools
            ),
        ]

    def _handler_for(self, name: str) -> Callable[[int, dict[str, Any]], dict[str, Any]] | None:
        """Return the injected handler for ``name``, or None if not registered."""
        for spec in self._extra_tools:
            if spec["name"] == name:
                return spec["handler"]
        return None

    def run(self, question: str, pid: int) -> str:
        """Answer ``question`` about patient ``pid`` via the tool-use loop."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

        # Cumulative tool executions across the whole turn (every tool_result
        # appended counts once — success, failure, unknown, injected alike).
        tool_calls_made = 0
        # Derive the iteration bound from the budget so the final no-tools call
        # (made once the budget is spent) always fits before the safety cap.
        max_iterations = self._max_tool_calls + 2

        for _ in range(max_iterations):
            # Offer tools only while under budget; once spent, pass an empty
            # list so the model cannot call more tools and must answer as text.
            offer_tools = self._tools() if tool_calls_made < self._max_tool_calls else []
            resp = self._message_creator(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_SYSTEM_PROMPT,
                tools=offer_tools,
                messages=messages,
            )

            usage = getattr(resp, "usage", None)
            self._observer.record_model_response(
                getattr(usage, "input_tokens", 0) if usage else 0,
                getattr(usage, "output_tokens", 0) if usage else 0,
            )

            tool_uses = [
                block
                for block in resp.content
                if getattr(block, "type", None) == "tool_use"
            ]

            if not tool_uses:
                return "".join(
                    block.text
                    for block in resp.content
                    if getattr(block, "type", None) == "text"
                )

            messages.append({"role": "assistant", "content": resp.content})

            tool_results: list[dict[str, Any]] = []
            for block in tool_uses:
                # Every handled tool_use block counts against the budget.
                tool_calls_made += 1
                if block.name == "get_patient_summary":
                    # Fixed session pid — ignore any model-supplied input.
                    try:
                        summary = self._boundary(pid)
                    except Exception:
                        # Record the failure and feed an error result back so the
                        # model can respond; the loop must not crash.
                        self._observer.record_tool_call("get_patient_summary", False)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": "Failed to retrieve the patient summary.",
                            }
                        )
                    else:
                        self._observer.record_tool_call("get_patient_summary", True)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(summary),
                            }
                        )
                elif (handler := self._handler_for(block.name)) is not None:
                    # An injected chart tool. The session pid is fixed; the model
                    # supplies only tool_input. Failures become a tool error, not
                    # a crash — mirroring the summary error path above.
                    try:
                        result = handler(pid, block.input)
                    except Exception:
                        self._observer.record_tool_call(block.name, False)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": f"Failed to run tool: {block.name}",
                            }
                        )
                    else:
                        self._observer.record_tool_call(block.name, True)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            }
                        )
                else:
                    self._observer.record_tool_call(block.name, False)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": True,
                            "content": f"Unknown tool: {block.name}",
                        }
                    )

            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(
            f"Tool-use loop exceeded {max_iterations} iterations without a final answer."
        )
