"""Value objects shared across the Chihiros protocol layer.

Pure data — no Bluetooth, no Home Assistant, no aquarium logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class CommandId(IntEnum):
    """First byte of a frame. Only proven ids are listed."""

    CMD_5A = 0x5A  # manual brightness, mode switch, set time, status query
    CMD_A5 = 0xA5  # auto-schedule add/update/delete


class Mode(IntEnum):
    """Byte 5 (mode/subcommand) values that are proven to work."""

    MODE_SWITCH = 0x05      # [18|11|5, 255, 255] -> auto / manual / reset
    STATUS_QUERY = 0x04     # [1] -> runtime/status response (header 0x5B)
    MANUAL_CHANNEL = 0x07   # [channel, brightness]
    SET_TIME = 0x09         # [year-2000, month, weekday, hour, min, sec]
    AUTO_SCHEDULE = 0x19    # 14-byte schedule payload (used with CMD_A5)


# Mode-switch sub-selectors (first parameter byte of a MODE_SWITCH command).
MODE_SWITCH_AUTO = 18
MODE_SWITCH_MANUAL = 11
MODE_SWITCH_RESET = 5


@dataclass(frozen=True, slots=True)
class RGBW:
    """An RGBW output, each channel 0..100 (percent)."""

    r: int = 0
    g: int = 0
    b: int = 0
    w: int = 0

    def __post_init__(self) -> None:
        for name, value in (("r", self.r), ("g", self.g), ("b", self.b), ("w", self.w)):
            if not 0 <= value <= 100:
                raise ValueError(f"channel {name}={value} out of range 0..100")

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.w)


# Weekday bitmask (matches the protocol; Monday is the high bit).
WEEKDAY_BITS = {
    0: 64,  # Monday   (Python weekday())
    1: 32,  # Tuesday
    2: 16,  # Wednesday
    3: 8,   # Thursday
    4: 4,   # Friday
    5: 2,   # Saturday
    6: 1,   # Sunday
}
WEEKDAYS_EVERY_DAY = 127
