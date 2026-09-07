"""Chihiros BLE protocol layer.

Pure, transport-agnostic encoding/decoding of the reverse-engineered local
BLE protocol. This package must not import Bluetooth libraries, Home
Assistant, or the aquarium Light Engine.
"""
from __future__ import annotations

from .checksum import xor_checksum
from .commands import (
    MessageIdCounter,
    build_frame,
    enter_auto_mode,
    enter_manual_mode,
    query_status,
    reset_auto_settings,
    set_channel_brightness,
    set_rgbw,
    set_time,
)
from .models import RGBW, CommandId, Mode
from .parser import RawResponse, StatusResponse, parse_notification

__all__ = [
    "RGBW",
    "CommandId",
    "MessageIdCounter",
    "Mode",
    "RawResponse",
    "StatusResponse",
    "build_frame",
    "enter_auto_mode",
    "enter_manual_mode",
    "parse_notification",
    "query_status",
    "reset_auto_settings",
    "set_channel_brightness",
    "set_rgbw",
    "set_time",
    "xor_checksum",
]
