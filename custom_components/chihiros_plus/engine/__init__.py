"""Aquarium Light Engine — the generic day-simulation core.

Pure and self-contained: no Home Assistant, no Bluetooth. Programs supply
parameters; this package turns them into a desired light state at any moment.
"""
from __future__ import annotations

from .light_engine import LightEngine, LightState
from .phases import Phase
from .programs import PRESETS, MiddayPause, ProgramParameters

__all__ = [
    "PRESETS",
    "LightEngine",
    "LightState",
    "MiddayPause",
    "Phase",
    "ProgramParameters",
]
