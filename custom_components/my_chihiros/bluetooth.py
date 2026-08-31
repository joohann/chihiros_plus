"""Real Home Assistant Bluetooth transport for a Chihiros lamp.

Implements the ``Transport`` protocol (see transport.py) on top of Home
Assistant's Bluetooth stack and bleak-retry-connector, so it works with the
host adapter and ESPHome Bluetooth proxies alike. This is the only place that
imports bleak; the watchdog/controller/engine above it stay BLE-agnostic and
unit-testable without hardware.

Confirmation: writes use ``response=True`` (write-with-response), which the
WRGB II Slim supports (verified on real hardware). A successful write means the
lamp acknowledged the frame — the strongest confirmation this device offers.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import UART_RX_CHAR_UUID, UART_TX_CHAR_UUID
from .protocol.parser import parse_notification
from .transport import TransportError

_LOGGER = logging.getLogger(__name__)

NotifyHandler = Callable[[object], None]


class HAChihirosTransport:
    """A ``Transport`` implementation using HA Bluetooth + bleak-retry-connector."""

    def __init__(
        self,
        ble_device: BLEDevice,
        name: str,
        *,
        notify_handler: NotifyHandler | None = None,
    ) -> None:
        self._ble_device = ble_device
        self._name = name
        self._notify_handler = notify_handler
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._rssi: int | None = None

    # -- link state ----------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def rssi(self) -> int | None:
        return self._rssi

    def update_ble_device(self, ble_device: BLEDevice, rssi: int | None) -> None:
        """Refresh the BLEDevice/rssi from a new advertisement (called by HA)."""
        self._ble_device = ble_device
        if rssi is not None:
            self._rssi = rssi

    # -- connection ----------------------------------------------------------

    async def connect(self) -> None:
        if self.is_connected:
            return
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self._name,
                self._on_disconnect,
                use_services_cache=True,
            )
        except (BleakError, asyncio.TimeoutError, OSError) as err:
            raise TransportError(f"connect failed: {err}") from err
        self._client = client
        try:
            await client.start_notify(UART_TX_CHAR_UUID, self._on_notify)
        except (BleakError, OSError) as err:  # notifications are non-fatal
            _LOGGER.debug("%s: could not enable notifications: %s", self._name, err)

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except (BleakError, OSError) as err:  # pragma: no cover - best effort
                _LOGGER.debug("%s: disconnect error: %s", self._name, err)

    async def send(self, frame: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise TransportError("not connected")
        async with self._lock:
            try:
                await client.write_gatt_char(UART_RX_CHAR_UUID, frame, response=True)
            except (BleakError, asyncio.TimeoutError, OSError) as err:
                raise TransportError(f"write failed: {err}") from err

    # -- callbacks -----------------------------------------------------------

    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        _LOGGER.debug("%s: disconnected", self._name)
        self._client = None

    def _on_notify(self, _char: object, data: bytearray) -> None:
        if self._notify_handler is None:
            return
        try:
            self._notify_handler(parse_notification(bytes(data)))
        except Exception:  # pragma: no cover - never let a notify crash us
            _LOGGER.exception("%s: notify handler error", self._name)
