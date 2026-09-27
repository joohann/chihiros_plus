"""Pure (HA-free) mode persist/restore logic for the coordinator.

The coordinator remembers whether the lamp is running its program, holding a
manual colour, or off, so a Home Assistant restart doesn't silently resume the
program (which, with all-night Moonlight, would burn all night after every
reboot — the bug fixed in v0.8.4).

The actual mapping lives here, with no ``homeassistant.*`` imports, so it can
be unit-tested in isolation. The coordinator calls these functions, so the
tested logic is the real logic — not a copy.
"""
from __future__ import annotations

from typing import Any

from .protocol import RGBW

MODE_PROGRAM = "program"
MODE_MANUAL = "manual"
MODE_OFF = "off"


def _coerce_manual(saved_manual: Any) -> RGBW:
    """Turn a persisted 4-tuple/list into a clamped RGBW (default: off)."""
    if isinstance(saved_manual, (list, tuple)) and len(saved_manual) == 4:
        return RGBW(*(max(0, min(100, int(c))) for c in saved_manual))
    return RGBW(0, 0, 0, 0)


def restore_mode(
    saved_mode: Any, saved_manual: Any, has_treatment: bool
) -> tuple[str, RGBW]:
    """Map persisted state to the mode (and manual colour) to start in.

    A running treatment always implies program mode, so it wins over any saved
    off/manual state. Otherwise a saved ``manual``/``off`` mode is restored
    (with its colour); anything else falls back to the program.
    """
    if has_treatment:
        return MODE_PROGRAM, RGBW(0, 0, 0, 0)
    if saved_mode in (MODE_MANUAL, MODE_OFF):
        return saved_mode, _coerce_manual(saved_manual)
    return MODE_PROGRAM, RGBW(0, 0, 0, 0)


def persist_mode_options(
    options: dict, mode: str, manual: RGBW
) -> dict:
    """Return a new options dict with the current mode (and manual colour when
    manual/off) written in, so a restart restores it instead of the program."""
    opts = {**options, "mode": mode}
    if mode in (MODE_MANUAL, MODE_OFF):
        opts["manual"] = list(manual.as_tuple())
    else:
        opts.pop("manual", None)
    return opts
