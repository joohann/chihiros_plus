"""Chihiros WRGB II Pro — RGBW, same local BLE protocol as the WRGB II Slim.

Verified against real hardware (advertised name prefix DYWPRO; per-channel RGBW
manual control over the shared Nordic-UART protocol works).
"""
from __future__ import annotations

from .base import ChihirosModel, register

WRGB_II_PRO = register(
    ChihirosModel(
        key="wrgb_ii_pro",
        name="WRGB II Pro",
        channels=("Red", "Green", "Blue", "White"),
        supports_rgb=True,
        supports_white=True,
        supports_moonlight=True,
        name_prefixes=("DYWPRO",),
    )
)
