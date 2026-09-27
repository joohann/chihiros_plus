"""Mode persistence tests: off / manual colour must survive a restart (v0.8.4).

A "restart" is simulated the way the coordinator does it: the options written
by ``persist_mode_options`` are fed back into ``restore_mode`` exactly as
``ChihirosCoordinator.__init__`` reads them from the config entry.
"""
from __future__ import annotations

from chihiros_plus.mode_state import (
    MODE_MANUAL,
    MODE_OFF,
    MODE_PROGRAM,
    persist_mode_options,
    restore_mode,
)

# Options as a real entry carries them: all-night moonlight program selected.
BASE = {"program": "natural_day", "moonlight": True, "moonlight_mode": "all_night"}
OFF = (0, 0, 0, 0)


def _restart(options: dict) -> tuple[str, tuple[int, int, int, int] | None]:
    return restore_mode(
        options.get("mode"),
        options.get("manual"),
        has_treatment=bool(options.get("treatment")),
    )


def test_off_persists_across_restart():
    opts = persist_mode_options(BASE, MODE_OFF, OFF)
    assert opts["mode"] == MODE_OFF
    assert opts["manual"] == [0, 0, 0, 0]
    assert opts["moonlight"] is True  # other options untouched
    assert _restart(opts) == (MODE_OFF, OFF)


def test_manual_colour_persists_across_restart():
    opts = persist_mode_options(BASE, MODE_MANUAL, (10, 20, 30, 40))
    assert _restart(opts) == (MODE_MANUAL, (10, 20, 30, 40))


def test_restored_manual_colour_is_clamped():
    assert restore_mode(MODE_MANUAL, [-5, 50, 150, "7"], False) == (
        MODE_MANUAL,
        (0, 50, 100, 7),
    )


def test_saved_mode_without_valid_colour_keeps_default():
    assert restore_mode(MODE_OFF, None, False) == (MODE_OFF, None)
    assert restore_mode(MODE_MANUAL, [1, 2, 3], False) == (MODE_MANUAL, None)


def test_fresh_entry_starts_in_program_mode():
    assert _restart(dict(BASE)) == (MODE_PROGRAM, None)


def test_persisting_program_mode_clears_saved_off():
    # e.g. async_apply_custom_program -> _persist_mode() in program mode
    off = persist_mode_options(BASE, MODE_OFF, OFF)
    opts = persist_mode_options(off, MODE_PROGRAM, OFF)
    assert opts["mode"] == MODE_PROGRAM
    assert "manual" not in opts
    assert _restart(opts) == (MODE_PROGRAM, None)


def test_selecting_program_clears_saved_off():
    # async_set_program & co. merge mode=program into the options directly,
    # leaving the stale manual colour behind; it must not be restored.
    off = persist_mode_options(BASE, MODE_OFF, OFF)
    opts = {**off, "program": "moonlight", "mode": MODE_PROGRAM}
    assert _restart(opts) == (MODE_PROGRAM, None)


def test_active_treatment_forces_program_over_saved_off():
    opts = persist_mode_options(BASE, MODE_OFF, OFF)
    opts["treatment"] = {"program": "blackout", "days": 3, "started": "2026-09-01T00:00:00+00:00"}
    assert _restart(opts) == (MODE_PROGRAM, None)


def test_active_treatment_forces_program_over_saved_manual():
    opts = persist_mode_options(BASE, MODE_MANUAL, (10, 20, 30, 40))
    opts["treatment"] = {"program": "blackout", "days": 3, "started": "2026-09-01T00:00:00+00:00"}
    assert _restart(opts) == (MODE_PROGRAM, None)
