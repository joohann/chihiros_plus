"""Frame checksum for the Chihiros BLE protocol.

The checksum is a simple XOR/BCC over the frame *excluding* byte 0 (the
command id) up to and including the last payload byte. This matches the
reference implementation in TheMicDiet/chihiros-led-control.

Nothing here knows about Bluetooth or aquarium logic — it is pure bytes.
"""
from __future__ import annotations

from collections.abc import Sequence


def xor_checksum(frame_without_checksum: Sequence[int]) -> int:
    """Return the XOR of bytes[1:] of a frame that has no checksum byte yet.

    ``frame_without_checksum`` is the full frame from the command id up to
    the last payload byte (i.e. everything except the trailing checksum).
    Byte 0 (command id) is excluded from the XOR, matching the protocol.
    """
    if len(frame_without_checksum) < 2:
        raise ValueError("frame too short to checksum")
    checksum = frame_without_checksum[1]
    for byte in frame_without_checksum[2:]:
        checksum ^= byte
    return checksum & 0xFF
