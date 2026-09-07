"""In-memory Chihiros lamp simulator.

Decodes the frames our protocol layer emits and tracks the resulting state,
so the engine, protocol, controller and (eventually) the watchdog can be
exercised in unit tests and a demo mode without physical hardware.

It validates checksums the same way the real lamp is understood to, and can
produce a status-query response. It is intentionally strict: an unknown or
corrupt frame raises, so tests catch encoding regressions early.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .protocol.checksum import xor_checksum
from .protocol.models import (
    MODE_SWITCH_AUTO,
    MODE_SWITCH_MANUAL,
    MODE_SWITCH_RESET,
    CommandId,
    Mode,
)
from .protocol.parser import RESPONSE_HEADER


class FrameError(ValueError):
    """Raised for a malformed or unrecognised frame."""


@dataclass
class FakeChihirosDevice:
    """A simulated WRGB II Slim (RGBW)."""

    channels: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    mode: str = "manual"          # "manual" | "auto"
    runtime_minutes: int = 0
    device_time: tuple[int, int, int, int, int, int] | None = None  # y,mo,wd,h,mi,s
    schedule: bytes | None = None
    frames_received: int = 0
    last_frame: bytes | None = None

    def write(self, frame: bytes) -> None:
        """Apply a command frame. Raises FrameError on anything invalid."""
        if len(frame) < 7:
            raise FrameError(f"frame too short: {frame.hex()}")
        if xor_checksum(frame[:-1]) != frame[-1]:
            raise FrameError(f"bad checksum: {frame.hex()}")
        self.frames_received += 1
        self.last_frame = frame

        cmd, mode = frame[0], frame[5]
        params = list(frame[6:-1])

        if cmd == CommandId.CMD_5A and mode == Mode.MANUAL_CHANNEL:
            channel, brightness = params
            if not 0 <= channel <= 3 or not 0 <= brightness <= 100:
                raise FrameError(f"manual params out of range: {params}")
            self.channels[channel] = brightness
            self.mode = "manual"
            return
        if cmd == CommandId.CMD_5A and mode == Mode.MODE_SWITCH:
            selector = params[0]
            if selector == MODE_SWITCH_MANUAL:
                self.mode = "manual"
            elif selector == MODE_SWITCH_AUTO:
                self.mode = "auto"
            elif selector == MODE_SWITCH_RESET:
                self.schedule = None
            else:
                raise FrameError(f"unknown mode selector: {selector}")
            return
        if cmd == CommandId.CMD_5A and mode == Mode.SET_TIME:
            self.device_time = tuple(params)  # type: ignore[assignment]
            return
        if cmd == CommandId.CMD_5A and mode == Mode.STATUS_QUERY:
            return  # response fetched separately via status_response()
        if cmd == CommandId.CMD_A5 and mode == Mode.AUTO_SCHEDULE:
            self.schedule = frame
            return
        raise FrameError(f"unhandled cmd/mode 0x{cmd:02x}/0x{mode:02x}")

    def status_response(self) -> bytes:
        """Build a plausible status-query reply (header 0x5b, runtime bytes)."""
        rt = self.runtime_minutes & 0xFFFF
        body = [RESPONSE_HEADER, 0x01, 0x08, 0x00, 0x00, Mode.STATUS_QUERY,
                rt >> 8, rt & 0xFF]
        return bytes([*body, xor_checksum(body)])
