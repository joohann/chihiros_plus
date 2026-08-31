"""Aquarium Light Engine tests: ramps, phases, moonlight bounding, night."""
from __future__ import annotations

from datetime import datetime

from aqua_chihiros.engine import LightEngine, Phase
from aqua_chihiros.engine.programs import NATURAL_DAY, MOONLIGHT


def _at(engine: LightEngine, hour: int, minute: int = 0):
    return engine.get_state(datetime(2026, 8, 31, hour, minute))


def test_night_before_start_is_off():
    e = LightEngine(NATURAL_DAY)
    s = _at(e, 5, 0)
    assert s.phase is Phase.NIGHT
    assert s.brightness == 0
    assert (s.r, s.g, s.b, s.w) == (0, 0, 0, 0)
    assert s.next_phase is Phase.SUNRISE


def test_sunrise_ramps_up_monotonically():
    e = LightEngine(NATURAL_DAY)  # start 07:00, sunrise 60m
    b0 = _at(e, 7, 0).brightness
    b15 = _at(e, 7, 15).brightness
    b45 = _at(e, 7, 45).brightness
    assert b0 == 0
    assert b0 < b15 < b45
    assert _at(e, 7, 15).phase is Phase.SUNRISE


def test_peak_holds_max_intensity():
    e = LightEngine(NATURAL_DAY)  # peak from 08:00 to 16:00, max 80
    s = _at(e, 12, 0)
    assert s.phase is Phase.PEAK
    assert s.brightness == 80
    # peak colour reached exactly at peak
    assert (s.r, s.g, s.b, s.w) == (70, 65, 85, 40)


def test_sunset_ramps_down():
    e = LightEngine(NATURAL_DAY)  # sunset 16:00->17:00
    b16 = _at(e, 16, 0).brightness
    b1630 = _at(e, 16, 30).brightness
    b17 = _at(e, 17, 0).brightness
    assert b16 == 80
    assert b16 > b1630 > b17
    assert _at(e, 16, 30).phase is Phase.SUNSET


def test_moonlight_window_active_then_night():
    e = LightEngine(NATURAL_DAY)  # day ends 17:00, moonlight 120m -> 19:00
    moon = _at(e, 18, 0)
    assert moon.phase is Phase.MOONLIGHT
    assert moon.brightness == 5
    # blue-biased moonlight, scaled so the brightest channel == intensity (5%)
    assert moon.b == 5
    assert moon.b >= moon.r and moon.b >= moon.g
    # after the window: fully off (bounded moonlight)
    after = _at(e, 20, 0)
    assert after.phase is Phase.NIGHT
    assert after.brightness == 0


def test_moonlight_cannot_run_all_night():
    e = LightEngine(NATURAL_DAY)
    # every hour from 20:00 to 06:00 must be NIGHT/off
    for h in list(range(20, 24)) + list(range(0, 7)):
        assert _at(e, h, 0).brightness == 0


def test_dedicated_moonlight_program_has_no_daytime():
    e = LightEngine(MOONLIGHT)  # start 20:00, 4h moon, no day
    assert _at(e, 12, 0).brightness == 0
    night_moon = _at(e, 21, 0)
    assert night_moon.phase is Phase.MOONLIGHT
    assert night_moon.brightness == 8


def test_channels_scale_with_brightness():
    e = LightEngine(NATURAL_DAY)
    mid = _at(e, 7, 30)  # halfway up sunrise-ish
    # channels are peak colour scaled by brightness/max, never exceeding peak
    assert 0 < mid.r < 70
    assert mid.brightness > 0
