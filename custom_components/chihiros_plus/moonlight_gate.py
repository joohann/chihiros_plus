"""Helper/switch gating for Moonlight-at-night.

Pure decision logic (no Home Assistant import) so it can be unit tested:

* ``"switch"``: moonlight glows only while the helper is in the chosen state
  (on, or off when inverted), re-evaluated every tick.
* ``"until_switch"``: moonlight glows from lights-off until the helper turns
  on (e.g. a "Night mode" that switches the whole house off), then stays off
  for the rest of that night — even if the helper turns off again in the
  morning before the next lights-on. The latch resets outside the moonlight
  window.
"""
from __future__ import annotations

SWITCH_MODES = ("switch", "until_switch")


def moonlight_gate(
    mode: str,
    *,
    in_moonlight: bool,
    helper_on: bool,
    invert: bool = False,
    latched: bool = False,
) -> tuple[bool, bool]:
    """Return ``(glow, latched)`` for the current tick."""
    if not in_moonlight:
        return True, False  # nothing to gate; a new night starts un-latched
    if mode == "switch":
        return ((not helper_on) if invert else helper_on), False
    if mode == "until_switch":
        latched = latched or helper_on
        return not latched, latched
    return True, False
