"""Controller tests: desired vs confirmed, calibration, dedupe, emergency off."""
from __future__ import annotations

import asyncio

from aqua_chihiros.controller import Calibration, LightController
from aqua_chihiros.protocol import RGBW
from aqua_chihiros.transport import FakeTransport
from aqua_chihiros.watchdog import Watchdog, WatchdogConfig


async def _no_sleep(_s: float) -> None:
    return None


def _controller(transport, calibration=None):
    wd = Watchdog(transport, WatchdogConfig(max_retries=2), sleep=_no_sleep)
    return LightController("Left", wd, calibration=calibration)


def test_apply_sets_channels_and_confirms():
    tr = FakeTransport()
    c = _controller(tr)
    ok = asyncio.run(c.apply_rgbw(RGBW(10, 20, 30, 40)))
    assert ok is True
    assert tr.device.channels == [10, 20, 30, 40]
    assert tr.device.mode == "manual"  # controller asserted manual mode first
    assert c.confirmed == RGBW(10, 20, 30, 40)
    assert c.is_confirmed is True


def test_calibration_scales_output():
    tr = FakeTransport()
    c = _controller(tr, Calibration(scale_r=0.5, scale_w=0.0))
    asyncio.run(c.apply_rgbw(RGBW(100, 80, 60, 100)))
    assert tr.device.channels == [50, 80, 60, 0]


def test_unchanged_target_is_not_resent():
    tr = FakeTransport()
    c = _controller(tr)
    asyncio.run(c.apply_rgbw(RGBW(10, 20, 30, 40)))
    sent_after_first = len(tr.sent_frames)
    asyncio.run(c.apply_rgbw(RGBW(10, 20, 30, 40)))  # identical -> skipped
    assert len(tr.sent_frames) == sent_after_first


def test_changed_target_is_resent():
    tr = FakeTransport()
    c = _controller(tr)
    asyncio.run(c.apply_rgbw(RGBW(10, 20, 30, 40)))
    n = len(tr.sent_frames)
    asyncio.run(c.apply_rgbw(RGBW(11, 20, 30, 40)))
    # enter_manual + four channel frames
    assert len(tr.sent_frames) == n + 5


def test_failed_command_leaves_confirmed_unknown():
    tr = FakeTransport()
    tr.offline = True
    c = _controller(tr)
    ok = asyncio.run(c.apply_rgbw(RGBW(10, 20, 30, 40)))
    assert ok is False
    assert c.confirmed is None          # UNKNOWN, never fabricated
    assert c.desired == RGBW(10, 20, 30, 40)
    assert c.is_confirmed is False


def test_emergency_off_forces_zero():
    tr = FakeTransport()
    c = _controller(tr)
    asyncio.run(c.apply_rgbw(RGBW(80, 80, 80, 80)))
    ok = asyncio.run(c.emergency_off())
    assert ok is True
    assert tr.device.channels == [0, 0, 0, 0]


def test_emergency_off_reports_failure_when_unreachable():
    tr = FakeTransport()
    tr.offline = True
    c = _controller(tr)
    ok = asyncio.run(c.emergency_off())
    assert ok is False                  # cannot guarantee off with no link
    assert c.confirmed is None
