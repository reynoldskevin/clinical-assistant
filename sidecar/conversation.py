"""Ephemeral, pid-scoped, TTL-bounded conversation store for multi-turn context.

Follow-up questions ("is that normal?") need the prior turn's messages, but the
sidecar must not become stateful long-term and must never leak one patient's
context into another's conversation. This store keeps message history in memory
for a short TTL window, keyed by conversation id and scoped to the pid that
created it, then expires. Nothing is persisted to disk (no PHI at rest).

An injectable clock (defaulting to ``time.monotonic``) makes TTL expiry
deterministically testable.
"""
from __future__ import annotations

import time
from typing import Callable


class ConversationStore:
    """In-memory conversation history with a per-entry TTL and pid scoping."""

    def __init__(
        self,
        ttl_seconds: float = 600.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        # conversation_id -> (pid, messages, expires_at)
        self._entries: dict[str, tuple[int, list, float]] = {}

    def remember(self, conversation_id: str, pid: int, messages: list) -> None:
        """Store a COPY of ``messages`` for ``conversation_id``, scoped to ``pid``.

        A copy is taken so later external mutation of the caller's list cannot
        corrupt the stored conversation.
        """
        expires_at = self._clock() + self._ttl_seconds
        self._entries[conversation_id] = (pid, list(messages), expires_at)

    def history(self, conversation_id: str, pid: int) -> list | None:
        """Return a COPY of the stored messages, or None.

        Returns None (and never the internal list) unless the entry exists, is
        within its TTL, and was stored under the same ``pid``. An expired entry
        is evicted before returning None; a pid mismatch returns None WITHOUT
        evicting (so the legitimate owner can still read it).
        """
        entry = self._entries.get(conversation_id)
        if entry is None:
            return None

        stored_pid, messages, expires_at = entry
        if self._clock() >= expires_at:
            del self._entries[conversation_id]
            return None
        if stored_pid != pid:
            return None
        return list(messages)
