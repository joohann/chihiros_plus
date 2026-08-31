"""Day phases produced by the Aquarium Light Engine.

A phase is a human-readable label for where in the simulated day a moment
falls. It is derived from the program's anchor times, not stored per program,
so any program built on the engine gets the same phase vocabulary.
"""
from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    DAWN = "dawn"          # before the lights begin to rise
    SUNRISE = "sunrise"    # ramping up
    MORNING = "morning"    # risen, before peak hold
    PEAK = "peak"          # midday hold at max intensity
    AFTERNOON = "afternoon"  # after peak hold, before sunset
    SUNSET = "sunset"      # ramping down
    DUSK = "dusk"          # just after lights off, before moonlight
    MOONLIGHT = "moonlight"
    NIGHT = "night"        # everything off
