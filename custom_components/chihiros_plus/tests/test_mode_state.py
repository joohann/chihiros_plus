"""Regression tests locking in the v0.8.4 fix: an off/manual state must survive
a Home Assistant restart instead of the coordinator silently falling back to
the program (which, with all-night Moonlight, left the light burning all night
after every reboot).

The coordinator itself imports ``homeassistant.*``; these tests exercise the
pure persist/restore logic the coordinator delegates to (``mode_state``), so
the behaviour under test is the real behaviour, not a copy. We simulate a
restart by feeding the persisted options back through ``restore_mode`` — exactly
what ``ChihirosCoordinator.__init__`` does on startup.
"""
from __future__ import annotations

from chihiros_plus.mode_state import (
    MODE_MANUAL,
    MODE_OFF,
    MODE_PROGRAM,
    persist_mode_options,
    restore_mode,
)
from chihiros_plus.protocol import RGBW


def _restart(options: dict, *, has_treatment: bool = False) -> tuple[str, RGBW]:
    """What a fresh coordinator restores from the persisted entry options."""
    return restore_mode(
        options.get("mode"), options.get("manual"), has_treatment
    )


def test_off_state_persists_across_restart():
    # async_set_manual_rgbw(RGBW(0,0,0,0)) -> MODE_OFF, then _persist_mode().
    opts = persist_mode_options({"program": "natural_day"}, MODE_OFF, RGBW(0, 0, 0, 0))
    assert opts["mode"] == MODE_OFF
    assert opts["manual"] == [0, 0, 0, 0]

    mode, manual = _restart(opts)
    assert mode == MODE_OFF
    assert manual == RGBW(0, 0, 0, 0)  # stays off, program does not resume


def test_manual_colour_persists_across_restart():
    color = RGBW(30, 40, 50, 60)
    opts = persist_mode_options({}, MODE_MANUAL, color)
    assert opts["mode"] == MODE_MANUAL
    assert opts["manual"] == [30, 40, 50, 60]

    mode, manual = _restart(opts)
    assert mode == MODE_MANUAL
    assert manual == color


def test_program_mode_clears_saved_off_manual():
    # Start from a persisted OFF state...
    opts = persist_mode_options({}, MODE_OFF, RGBW(0, 0, 0, 0))
    # ...then a program-selecting method writes mode=program into options,
    # which must clear the stale manual colour so it can't reappear on reboot.
    opts = {**opts, "program": "natural_day", "mode": MODE_PROGRAM}
    opts.pop("manual", None)

    mode, manual = _restart(opts)
    assert mode == MODE_PROGRAM
    assert "manual" not in opts


def test_active_treatment_forces_program_mode():
    # Even with a saved OFF state, a running treatment wins on restart.
    opts = persist_mode_options({}, MODE_OFF, RGBW(0, 0, 0, 0))
    mode, manual = _restart(opts, has_treatment=True)
    assert mode == MODE_PROGRAM
    assert manual == RGBW(0, 0, 0, 0)


def test_no_saved_mode_falls_back_to_program():
    mode, manual = _restart({"program": "natural_day"})
    assert mode == MODE_PROGRAM


def test_persist_program_mode_drops_manual_key():
    opts = persist_mode_options({"manual": [10, 10, 10, 10]}, MODE_PROGRAM, RGBW(0, 0, 0, 0))
    assert opts["mode"] == MODE_PROGRAM
    assert "manual" not in opts


def test_restore_clamps_out_of_range_manual():
    mode, manual = restore_mode(MODE_MANUAL, [200, -5, 50, 999], has_treatment=False)
    assert mode == MODE_MANUAL
    assert manual == RGBW(100, 0, 50, 100)
