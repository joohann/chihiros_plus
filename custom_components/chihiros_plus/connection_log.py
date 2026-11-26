"""A short history of the lamp's Bluetooth link.

Stored per lamp in Home Assistant's .storage by the coordinator, so the
history survives a restart.

Answers the question the connection sensor alone cannot: *when* did the link
drop, how long had it been idle before that, and how long did it take to come
back. Kept small (the most recent events only) and free of Home Assistant
imports so it can be unit-tested directly; the coordinator passes in wall-clock
timestamps as ISO strings.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass

EVENT_DISCONNECTED = "disconnected"
EVENT_RECONNECTED = "reconnected"
EVENT_RECONNECT_FAILED = "reconnect_failed"
# The link turned out to be gone when we next looked, but no drop was ever
# reported (the adapter or proxy never called back). The drop happened at some
# point during the idle time in ``seconds``.
EVENT_FOUND_DISCONNECTED = "found_disconnected"

DEFAULT_MAX_EVENTS = 100


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    kind: str
    at: str                              # ISO-8601 wall-clock time
    rssi: int | None = None
    source: str | None = None            # Bluetooth adapter / proxy that held the link
    seconds: float | None = None         # disconnected: idle since last write; reconnected: outage length
    detail: str | None = None            # last error, for a failed reconnect

    def as_dict(self) -> dict:
        data = asdict(self)
        if data["seconds"] is not None:
            data["seconds"] = round(data["seconds"], 1)
        return data


class ConnectionLog:
    """Ring buffer of link events, newest last."""

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._events: deque[ConnectionEvent] = deque(maxlen=max_events)

    def add(self, event: ConnectionEvent) -> None:
        self._events.append(event)

    def recent(self, limit: int | None = None) -> list[dict]:
        """The newest ``limit`` events (all when None), newest first."""
        events = list(self._events)[::-1]
        if limit is not None:
            events = events[:limit]
        return [e.as_dict() for e in events]

    def to_list(self) -> list[dict]:
        """All events, oldest first, for storage."""
        return [asdict(e) for e in self._events]

    def load(self, items: object) -> None:
        """Restore stored events (oldest first). Malformed entries are skipped."""
        if not isinstance(items, list):
            return
        fields = set(ConnectionEvent.__dataclass_fields__)
        for item in items:
            if not isinstance(item, dict) or not item.get("kind") or not item.get("at"):
                continue
            try:
                self._events.append(
                    ConnectionEvent(**{k: v for k, v in item.items() if k in fields})
                )
            except TypeError:
                continue

    def __len__(self) -> int:
        return len(self._events)
