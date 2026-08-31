"""Chihiros device abstraction layer.

Importing this package registers all known models. Pure data + a small
registry — no Home Assistant, no BLE.
"""
from __future__ import annotations

from .base import ChihirosModel, all_models, get_model, model_for_name
from .chihiros_wrgb_ii_slim import WRGB_II_SLIM

__all__ = [
    "WRGB_II_SLIM",
    "ChihirosModel",
    "all_models",
    "get_model",
    "model_for_name",
]
