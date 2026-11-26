"""Connection log: bounded, newest first, rounded durations."""
from __future__ import annotations

from chihiros_plus.connection_log import (
    EVENT_DISCONNECTED,
    EVENT_RECONNECTED,
    ConnectionEvent,
    ConnectionLog,
)


def test_newest_first_and_limit():
    log = ConnectionLog()
    log.add(ConnectionEvent(EVENT_DISCONNECTED, "2026-11-24T10:00:00+01:00", seconds=1799.94))
    log.add(ConnectionEvent(EVENT_RECONNECTED, "2026-11-24T10:00:01+01:00", seconds=0.83))
    recent = log.recent()
    assert [e["kind"] for e in recent] == [EVENT_RECONNECTED, EVENT_DISCONNECTED]
    assert recent[1]["seconds"] == 1799.9
    assert log.recent(1)[0]["kind"] == EVENT_RECONNECTED


def test_bounded():
    log = ConnectionLog(max_events=3)
    for i in range(5):
        log.add(ConnectionEvent(EVENT_DISCONNECTED, str(i)))
    assert len(log) == 3
    assert [e["at"] for e in log.recent()] == ["4", "3", "2"]


def test_round_trip_through_storage_and_skip_garbage():
    log = ConnectionLog()
    log.add(ConnectionEvent(EVENT_DISCONNECTED, "a", rssi=-60, source="proxy", seconds=12.0))
    log.add(ConnectionEvent(EVENT_RECONNECTED, "b", seconds=4.8))
    restored = ConnectionLog()
    restored.load(log.to_list() + [{"kind": ""}, "junk", {"kind": "x", "at": "c", "extra": 1}])
    assert [e["at"] for e in restored.recent()] == ["c", "b", "a"]
    assert restored.recent()[2]["source"] == "proxy"
    restored.load(None)          # nothing stored yet
    assert len(restored) == 3
