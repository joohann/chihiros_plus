"""Chihiros WRGB II Slim — the initial, hardware-verified model.

Verified against real hardware (advertised name prefix DYSL, Nordic UART
service, per-channel RGBW manual control, write-with-response acknowledgement).
"""
from __future__ import annotations

from .base import ChihirosModel, register

WRGB_II_SLIM = register(
    ChihirosModel(
        key="wrgb_ii_slim",
        name="WRGB II Slim",
        channels=("Red", "Green", "Blue", "White"),
        supports_rgb=True,
        supports_white=True,
        supports_moonlight=True,
        name_prefixes=("DYSL", "DYSIL"),
    )
)
