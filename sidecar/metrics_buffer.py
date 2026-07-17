"""Bounded in-memory buffer of recent ``sidecar.events`` records.

The ``/metrics`` endpoint renders the Week-2 dashboard panels + the
extraction-failure alert on demand. Rather than re-parse logs, it reads from a
small, bounded ring buffer of the most recent structured events. The buffer is
fed by an :class:`EventBufferHandler` attached to the dedicated ``sidecar.events``
logger — so it captures the REAL :func:`events.log_event` emissions
(``{"event", "correlation_id", **fields}`` JSON) without any producer-side change.

Pure stdlib (``collections`` + ``json`` + ``logging``): no dependencies, no
network. The buffer evicts the oldest record past ``maxlen`` and hands out
isolated snapshots so a reader can never be perturbed by concurrent writes.
"""
from __future__ import annotations

import json
import logging
from collections import deque


class EventBuffer:
    """A bounded FIFO ring buffer of event records (dicts).

    Backed by a :class:`collections.deque` with a fixed ``maxlen``: appending
    past capacity silently evicts the oldest record. Snapshots are isolated
    shallow copies so callers can read a stable view while writes continue.
    """

    def __init__(self, maxlen: int) -> None:
        self.maxlen = maxlen
        self._deque: deque[dict] = deque(maxlen=maxlen)

    def add(self, record: dict) -> None:
        """Append a record, evicting the oldest once ``maxlen`` is exceeded."""
        self._deque.append(record)

    def snapshot(self) -> list[dict]:
        """Return an isolated shallow copy of the current records as a new list.

        The returned list is independent of the buffer: neither mutating it nor
        subsequent :meth:`add` calls affect it (and vice versa). Copying the
        deque into a fresh ``list`` gives that isolation.
        """
        return list(self._deque)

    def __len__(self) -> int:
        return len(self._deque)


class EventBufferHandler(logging.Handler):
    """A logging handler that parses JSON log lines into an :class:`EventBuffer`.

    Each emitted record's message is expected to be the JSON object
    :func:`events.log_event` writes. A message that is not valid JSON (or any
    other emit error) is SILENTLY ignored — no record is added and nothing is
    raised — so a stray non-event log line on the same logger can never break
    the request path.
    """

    def __init__(self, buffer: EventBuffer) -> None:
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            parsed = json.loads(record.getMessage())
            self._buffer.add(parsed)
        except Exception:  # noqa: BLE001 - a non-JSON line must not raise
            return


def install_event_buffer(maxlen: int = 1000) -> EventBuffer:
    """Install a fresh :class:`EventBufferHandler` on the ``sidecar.events`` logger.

    Creates an :class:`EventBuffer`, removes any :class:`EventBufferHandler`
    already attached to ``sidecar.events`` (so repeated installs REPLACE rather
    than stack), attaches a new handler feeding the buffer, ensures the logger
    level is at most ``INFO`` (events are emitted at INFO), and returns the
    buffer for the ``/metrics`` consumer to read.
    """
    buffer = EventBuffer(maxlen=maxlen)
    logger = logging.getLogger("sidecar.events")
    for handler in list(logger.handlers):
        if isinstance(handler, EventBufferHandler):
            logger.removeHandler(handler)
    logger.addHandler(EventBufferHandler(buffer))
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    return buffer
