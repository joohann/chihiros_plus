"""Watchdog tests: retry ladder, state transitions, notification thresholds."""
from __future__ import annotations

import asyncio

from chihiros_plus.protocol import MessageIdCounter, set_channel_brightness
from chihiros_plus.transport import FakeTransport
from chihiros_plus.watchdog import ConnectionState, Watchdog, WatchdogConfig


class Clock:
    """Manually advanced monotonic clock for deterministic tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _wd(transport, clock=None):
    async def no_sleep(_seconds: float) -> None:  # never actually wait in tests
        return None

    return Watchdog(
        transport,
        WatchdogConfig(max_retries=3, retry_interval=5.0),
        clock=clock or Clock(),
        sleep=no_sleep,
    )


def _frame():
    return set_channel_brightness(0, 50, MessageIdCounter())


def test_successful_send_connects_and_confirms():
    tr = FakeTransport()
    wd = _wd(tr)
    ok = asyncio.run(wd.execute([_frame()]))
    assert ok is True
    assert wd.status.state is ConnectionState.CONNECTED
    assert wd.status.retry_count == 0
    assert wd.status.last_success is not None
    assert wd.status.rssi == -58


def test_recovers_after_transient_write_failures():
    tr = FakeTransport()
    asyncio.run(tr.connect())
    tr.fail_writes = 2  # first two writes fail, third attempt succeeds
    wd = _wd(tr)
    ok = asyncio.run(wd.execute([_frame()]))
    assert ok is True
    assert wd.status.state is ConnectionState.CONNECTED
    assert wd.status.retry_count >= 1  # needed at least one retry


def test_offline_device_reports_offline_after_retries():
    tr = FakeTransport()
    tr.offline = True
    wd = _wd(tr)
    ok = asyncio.run(wd.execute([_frame()]))
    assert ok is False
    assert wd.status.state is ConnectionState.OFFLINE
    assert tr.connect_calls >= 1  # attempted to reconnect


def test_reconnect_then_succeed():
    tr = FakeTransport()
    tr.offline = True
    wd = _wd(tr)

    async def scenario():
        # start offline; recover midway
        task_ok_first = await wd.execute([_frame()])
        tr.offline = False
        task_ok_second = await wd.execute([_frame()])
        return task_ok_first, task_ok_second

    first, second = asyncio.run(scenario())
    assert first is False
    assert second is True
    assert wd.status.state is ConnectionState.CONNECTED


def test_notification_thresholds_fire_once_each():
    clock = Clock()
    tr = FakeTransport()
    wd = _wd(tr, clock=clock)
    # establish a success baseline, then go offline
    asyncio.run(wd.execute([_frame()]))
    wd.status.state = ConnectionState.OFFLINE

    clock.advance(60)   # 1 min
    assert wd.poll_notification() is None
    clock.advance(70)   # 2m10s total -> warning
    ev = wd.poll_notification()
    assert ev is not None and ev.level == "warning"
    # no duplicate immediately
    assert wd.poll_notification() is None
    clock.advance(600)  # >10 min -> escalated warning
    ev2 = wd.poll_notification()
    assert ev2 is not None and ev2.threshold_seconds == wd.config.warning2_after
    clock.advance(1300)  # >30 min -> critical
    ev3 = wd.poll_notification()
    assert ev3 is not None and ev3.level == "critical"


def test_notifications_reset_after_recovery():
    clock = Clock()
    tr = FakeTransport()
    wd = _wd(tr, clock=clock)
    asyncio.run(wd.execute([_frame()]))
    wd.status.state = ConnectionState.OFFLINE
    clock.advance(200)
    assert wd.poll_notification() is not None      # warning fired
    asyncio.run(wd.execute([_frame()]))            # recovers
    assert wd.status.highest_notification_sent == 0.0
    assert wd.poll_notification() is None


def test_outage_is_timed_from_first_failure_not_last_success():
    # An idle, deduped link can go a long time without traffic. When the next
    # write finally fails, the outage starts *then* — not at the old success —
    # so we don't jump straight to "critical" with a misleading duration.
    clock = Clock()
    tr = FakeTransport()
    wd = _wd(tr, clock=clock)
    asyncio.run(wd.execute([_frame()]))
    clock.advance(3600)          # an hour of silence (output unchanged)
    tr.offline = True
    assert asyncio.run(wd.execute([_frame()])) is False
    assert wd.poll_notification() is None           # just detected
    clock.advance(130)
    ev = wd.poll_notification()
    assert ev is not None and ev.level == "warning"
    assert ev.threshold_seconds == wd.config.warning_after


def test_lamp_never_reached_since_startup_still_notifies():
    clock = Clock()
    tr = FakeTransport()
    tr.offline = True
    wd = _wd(tr, clock=clock)
    assert asyncio.run(wd.execute([_frame()])) is False
    assert wd.status.last_success is None
    clock.advance(130)
    ev = wd.poll_notification()
    assert ev is not None and ev.level == "warning"


def test_success_clears_outage_start():
    clock = Clock()
    tr = FakeTransport()
    tr.offline = True
    wd = _wd(tr, clock=clock)
    asyncio.run(wd.execute([_frame()]))
    assert wd.status.outage_since is not None
    tr.offline = False
    asyncio.run(wd.execute([_frame()]))
    assert wd.status.outage_since is None
