"""Transport abstraction between the device layer and the physical BLE link.

This defines the *interface* the controller and watchdog depend on, plus a
fake in-memory implementation for tests. The real Home Assistant Bluetooth
implementation (bluetooth.py, added in the HA build phase) implements the
same ``Transport`` protocol, so nothing above this line imports bleak or
Home Assistant.

Confirmation model: ``send()`` uses a write *with response*. Success means
the lamp acknowledged receipt at the BLE level — the strongest confirmation
this hardware offers, since it does not report its actual colour back. A
raised exception means we do NOT know the command took effect, and callers
must treat the resulting state as unconfirmed (UNKNOWN).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .fake_device import FakeChihirosDevice


class TransportError(Exception):
    """Raised when a BLE operation fails (connect or write)."""


@runtime_checkable
class Transport(Protocol):
    """The minimal link the device/watchdog layers need."""

    @property
    def is_connected(self) -> bool: ...

    @property
    def rssi(self) -> int | None: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send(self, frame: bytes) -> None:
        """Write one frame with response. Raise TransportError on failure."""
        ...


class FakeTransport:
    """In-memory transport backed by a FakeChihirosDevice, for tests/demo.

    Failure injection: set ``fail_writes`` to a positive int to make the next
    N ``send`` calls raise, or ``offline=True`` to fail connect + send until
    cleared. This lets watchdog retry/reconnect logic be tested deterministically.
    """

    def __init__(self, device: FakeChihirosDevice | None = None, rssi: int = -58) -> None:
        self.device = device or FakeChihirosDevice()
        self._connected = False
        self._rssi = rssi
        self.offline = False
        self.fail_writes = 0
        self.connect_calls = 0
        self.sent_frames: list[bytes] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def rssi(self) -> int | None:
        return self._rssi if self._connected else None

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.offline:
            self._connected = False
            raise TransportError("device offline")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, frame: bytes) -> None:
        if self.offline or not self._connected:
            raise TransportError("not connected")
        if self.fail_writes > 0:
            self.fail_writes -= 1
            raise TransportError("write failed (injected)")
        self.device.write(frame)  # raises FrameError on malformed frames
        self.sent_frames.append(frame)
