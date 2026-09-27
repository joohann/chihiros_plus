"""Persist / restore decision for the lamp mode across a Home Assistant restart.

Pure helpers (no Home Assistant import) so the restart behaviour can be unit
tested: turning the lamp off or setting a manual colour must survive a reboot
instead of silently falling back to the program — which, with all-night
moonlight, left the light burning all night after every restart.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MODE_PROGRAM = "program"
MODE_MANUAL = "manual"
MODE_OFF = "off"


def persist_mode_options(
    options: Mapping[str, Any], mode: str, manual: tuple[int, int, int, int]
) -> dict[str, Any]:
    """Return new entry options recording ``mode`` (and the manual colour when
    the mode is manual/off; a stale colour is dropped in program mode)."""
    opts = {**options, "mode": mode}
    if mode in (MODE_MANUAL, MODE_OFF):
        opts["manual"] = list(manual)
    else:
        opts.pop("manual", None)
    return opts


def restore_mode(
    saved_mode: Any, saved_manual: Any, has_treatment: bool
) -> tuple[str, tuple[int, int, int, int] | None]:
    """Decide the startup mode from persisted options.

    Returns ``(mode, manual)``; ``manual`` is ``None`` when no valid saved
    colour applies (the caller keeps its default). A running treatment always
    implies program mode, so it wins over a saved manual/off mode.
    """
    if has_treatment or saved_mode not in (MODE_MANUAL, MODE_OFF):
        return MODE_PROGRAM, None
    manual = None
    if isinstance(saved_manual, (list, tuple)) and len(saved_manual) == 4:
        manual = tuple(max(0, min(100, int(c))) for c in saved_manual)
    return saved_mode, manual
