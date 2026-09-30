"""Moonlight helper gating: "switch" (live) and "until_switch" (latching)."""
from __future__ import annotations

from chihiros_plus.moonlight_gate import moonlight_gate


def _night(mode, helper_states, invert=False):
    """Run one night tick-by-tick; return the glow value per tick."""
    latched, out = False, []
    for on in helper_states:
        glow, latched = moonlight_gate(
            mode, in_moonlight=True, helper_on=on, invert=invert, latched=latched
        )
        out.append(glow)
    return out, latched


def test_until_switch_glows_until_night_mode_then_stays_off():
    # evening: night mode off -> on (house goes dark) -> off again in the morning
    glow, latched = _night("until_switch", [False, False, True, True, False, False])
    assert glow == [True, True, False, False, False, False]
    assert latched is True


def test_until_switch_resets_for_the_next_night():
    _, latched = _night("until_switch", [False, True])
    # daytime tick outside the moonlight window clears the latch
    glow, latched = moonlight_gate(
        "until_switch", in_moonlight=False, helper_on=False, latched=latched
    )
    assert (glow, latched) == (True, False)
    glow, _ = moonlight_gate("until_switch", in_moonlight=True, helper_on=False, latched=latched)
    assert glow is True


def test_until_switch_respects_persisted_latch_after_restart():
    glow, latched = moonlight_gate(
        "until_switch", in_moonlight=True, helper_on=False, latched=True
    )
    assert (glow, latched) == (False, True)


def test_switch_mode_follows_helper_live_and_never_latches():
    glow, latched = _night("switch", [False, True, False])
    assert glow == [False, True, False]
    assert latched is False
    glow, _ = _night("switch", [False, True, False], invert=True)
    assert glow == [True, False, True]


def test_other_modes_are_not_gated():
    for mode in ("all_night", "duration", "time"):
        assert moonlight_gate(mode, in_moonlight=True, helper_on=True) == (True, False)
