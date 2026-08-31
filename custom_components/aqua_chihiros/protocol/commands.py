"""Encode Chihiros BLE command frames.

Every builder here produces a complete, checksummed frame ready to write to
the UART RX characteristic. This module is deliberately BLE-agnostic: it
returns ``bytes`` and never touches a Bluetooth stack. It also contains no
aquarium/scheduling logic — callers decide *what* to send; this decides
*how* the bytes look on the wire.

Frame layout (proven, docs/protocol.md):

    [0] command id            (0x5a / 0xa5)
    [1] tx marker             (0x01)
    [2] length                (len(params) + 5)
    [3] message id high
    [4] message id low
    [5] mode / subcommand
    [6..] parameters
    [-1] checksum             (xor of bytes[1:-1])

Message-id quirk: legacy firmware reserves 0x5a. If any of the two id bytes,
or the resulting checksum, equals 0x5a, we advance the id and rebuild.
"""
from __future__ import annotations

from collections.abc import Sequence
from itertools import count

from .checksum import xor_checksum
from .models import (
    MODE_SWITCH_AUTO,
    MODE_SWITCH_MANUAL,
    MODE_SWITCH_RESET,
    CommandId,
    Mode,
    RGBW,
)

TX_MARKER = 0x01
_RESERVED = 0x5A


class MessageIdCounter:
    """Rolling 16-bit message id, skipping ids that contain 0x5a.

    The lamp does not require strictly monotonic ids, but the reference
    implementation increments one per command; we keep our own so a single
    device connection produces a clean, debuggable sequence.
    """

    def __init__(self, start: int = 1) -> None:
        self._counter = count(start)
        self._value = start

    def _advance(self) -> int:
        self._value = next(self._counter) & 0xFFFF
        return self._value

    def next_id(self) -> tuple[int, int]:
        """Return (high, low) id bytes, neither of which is 0x5a."""
        hi, lo = self._value >> 8, self._value & 0xFF
        while hi == _RESERVED or lo == _RESERVED:
            self._advance()
            hi, lo = self._value >> 8, self._value & 0xFF
        # advance for next call so consecutive commands differ
        current = (hi, lo)
        self._advance()
        return current


def build_frame(
    command_id: int,
    mode: int,
    params: Sequence[int],
    msg_id: MessageIdCounter,
) -> bytes:
    """Assemble a checksummed frame, rebuilding if the checksum hits 0x5a."""
    for _ in range(64):  # bounded retry; ids recycle well within this
        hi, lo = msg_id.next_id()
        head = [command_id, TX_MARKER, len(params) + 5, hi, lo, mode, *params]
        checksum = xor_checksum(head)
        if checksum != _RESERVED:
            return bytes([*head, checksum])
    raise RuntimeError("could not find a message id yielding a non-0x5a checksum")


# --- High-level builders ----------------------------------------------------


def set_channel_brightness(
    channel: int, brightness: int, msg_id: MessageIdCounter
) -> bytes:
    """0x5a / 0x07 — set one channel (0..3) to a brightness (0..100)."""
    if not 0 <= channel <= 3:
        raise ValueError(f"channel {channel} out of range 0..3")
    if not 0 <= brightness <= 100:
        raise ValueError(f"brightness {brightness} out of range 0..100")
    return build_frame(
        CommandId.CMD_5A, Mode.MANUAL_CHANNEL, [channel, brightness], msg_id
    )


def set_rgbw(color: RGBW, msg_id: MessageIdCounter) -> list[bytes]:
    """Four MANUAL_CHANNEL frames, one per channel.

    Returned as an ordered list so the transport can send them back-to-back.
    The protocol has no proven single-shot RGBW frame, so we compose from the
    proven per-channel command rather than invent one.
    """
    return [
        set_channel_brightness(idx, value, msg_id)
        for idx, value in enumerate(color.as_tuple())
    ]


def enter_manual_mode(msg_id: MessageIdCounter) -> bytes:
    """0x5a / 0x05 with [11,255,255] — switch the lamp to manual control."""
    return build_frame(
        CommandId.CMD_5A, Mode.MODE_SWITCH, [MODE_SWITCH_MANUAL, 255, 255], msg_id
    )


def enter_auto_mode(msg_id: MessageIdCounter) -> bytes:
    """0x5a / 0x05 with [18,255,255] — run the on-device schedule (fail-safe)."""
    return build_frame(
        CommandId.CMD_5A, Mode.MODE_SWITCH, [MODE_SWITCH_AUTO, 255, 255], msg_id
    )


def reset_auto_settings(msg_id: MessageIdCounter) -> bytes:
    """0x5a / 0x05 with [5,255,255] — clear stored auto settings."""
    return build_frame(
        CommandId.CMD_5A, Mode.MODE_SWITCH, [MODE_SWITCH_RESET, 255, 255], msg_id
    )


def set_time(
    *,
    year: int,
    month: int,
    weekday: int,
    hour: int,
    minute: int,
    second: int,
    msg_id: MessageIdCounter,
) -> bytes:
    """0x5a / 0x09 — set the lamp's internal clock.

    ``weekday`` is ISO 1..7 (Monday..Sunday). ``year`` is the full year; the
    frame carries year-2000.
    """
    if not 2000 <= year <= 2255:
        raise ValueError(f"year {year} out of encodable range")
    if not 1 <= weekday <= 7:
        raise ValueError(f"weekday {weekday} must be ISO 1..7")
    params = [year - 2000, month, weekday, hour, minute, second]
    return build_frame(CommandId.CMD_5A, Mode.SET_TIME, params, msg_id)


def query_status(msg_id: MessageIdCounter) -> bytes:
    """0x5a / 0x04 with [1] — request the runtime/status response."""
    return build_frame(CommandId.CMD_5A, Mode.STATUS_QUERY, [1], msg_id)
