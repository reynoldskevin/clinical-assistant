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

# The response object returned by the message-creator (SDK Message shape).
MessageResponse = Any

# Callable signature: message_creator(model=, max_tokens=, system=, tools=, messages=).
MessageCreator = Callable[..., MessageResponse]

# Callable signature: boundary(pid) -> dict (the patient summary).
Boundary = Callable[[int], dict[str, Any]]

_MAX_ITERATIONS = 8

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
    ) -> None:
        self._message_creator = message_creator
        self._boundary = boundary
        self._model = model
        self._max_tokens = max_tokens

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
        ]

    def run(self, question: str, pid: int) -> str:
        """Answer ``question`` about patient ``pid`` via the tool-use loop."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

        for _ in range(_MAX_ITERATIONS):
            resp = self._message_creator(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_SYSTEM_PROMPT,
                tools=self._tools(),
                messages=messages,
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
                if block.name == "get_patient_summary":
                    # Fixed session pid — ignore any model-supplied input.
                    summary = self._boundary(pid)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(summary),
                        }
                    )
                else:
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
            f"Tool-use loop exceeded {_MAX_ITERATIONS} iterations without a final answer."
        )
