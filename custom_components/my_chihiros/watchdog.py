"""Bluetooth Watchdog — a core safety component, not an add-on.

The central safety concern for a BLE aquarium light is: Home Assistant loses
Bluetooth while the lamp stays on its last brightness, so it burns far longer
and brighter than intended. The watchdog actively guards against this by
wrapping every command in a retry/reconnect ladder, tracking how long the
lamp has been unreachable, and — crucially — never reporting a command as
confirmed unless the link acknowledged it.

The primary fail-safe against a total BLE loss is the lamp's *own* on-device
schedule (uploaded by the controller); this watchdog is the second layer,
covering manual control and surfacing the unreachable condition to the user.

This module is BLE- and HA-independent: it depends only on the ``Transport``
interface and injectable clock/sleep, so the whole ladder is unit-testable
with a fake transport.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from .const import (
    STATE_CONNECTED,
    STATE_DEGRADED,
    STATE_ERROR,
    STATE_OFFLINE,
    STATE_RECONNECTING,
    STATE_UNKNOWN,
)
from .fake_device import FrameError
from .transport import Transport, TransportError


class ConnectionState(str, Enum):
    CONNECTED = STATE_CONNECTED
    DEGRADED = STATE_DEGRADED
    RECONNECTING = STATE_RECONNECTING
    OFFLINE = STATE_OFFLINE
    ERROR = STATE_ERROR
    UNKNOWN = STATE_UNKNOWN


@dataclass(frozen=True, slots=True)
class WatchdogConfig:
    max_retries: int = 3
    retry_interval: float = 5.0        # seconds between retries
    warning_after: float = 120.0       # 2 min  -> warning notification
    warning2_after: float = 600.0      # 10 min -> escalated warning
    critical_after: float = 1800.0     # 30 min -> critical notification


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    level: str            # "warning" | "critical"
    elapsed_seconds: float
    threshold_seconds: float


@dataclass
class WatchdogStatus:
    state: ConnectionState = ConnectionState.UNKNOWN
    retry_count: int = 0            # retries used on the last operation
    consecutive_failures: int = 0
    last_success: float | None = None
    last_error: str | None = None
    rssi: int | None = None
    highest_notification_sent: float = field(default=0.0)  # threshold already fired


class Watchdog:
    """Guards a single transport/lamp link."""

    def __init__(
        self,
        transport: Transport,
        config: WatchdogConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.transport = transport
        self.config = config or WatchdogConfig()
        self._clock = clock
        self._sleep = sleep
        self.status = WatchdogStatus()

    # -- command execution with retry/reconnect ladder ----------------------

    async def execute(self, frames: Sequence[bytes]) -> bool:
        """Send frames, retrying and reconnecting on failure.

        Returns True only if every frame was acknowledged (the caller may then
        treat the result as confirmed). Returns False after exhausting retries,
        with ``status.state`` set to OFFLINE (could not connect) or ERROR
        (connected but writes keep failing).
        """
        last_err: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            self.status.retry_count = attempt
            try:
                if not self.transport.is_connected:
                    self._set_state(ConnectionState.RECONNECTING)
                    await self.transport.connect()
                for frame in frames:
                    await self.transport.send(frame)
                self._on_success()
                return True
            except (TransportError, FrameError) as err:
                last_err = err
                self._on_failure(err)
                if attempt >= self.config.max_retries:
                    break
                # Later attempts: drop the link so the next iteration reconnects.
                self._set_state(ConnectionState.RECONNECTING)
                try:
                    await self.transport.disconnect()
                except Exception:  # pragma: no cover - best effort
                    pass
                # First retry is immediate; subsequent ones wait.
                if attempt >= 1:
                    await self._sleep(self.config.retry_interval)
        self._finalize_failure(last_err)
        return False

    # -- state bookkeeping ---------------------------------------------------

    def _set_state(self, state: ConnectionState) -> None:
        self.status.state = state

    def _on_success(self) -> None:
        self.status.state = ConnectionState.CONNECTED
        self.status.consecutive_failures = 0
        self.status.last_success = self._clock()
        self.status.last_error = None
        self.status.rssi = self.transport.rssi
        self.status.highest_notification_sent = 0.0

    def _on_failure(self, err: Exception) -> None:
        self.status.consecutive_failures += 1
        self.status.last_error = str(err)
        # A single failure with retries left is "degraded", not offline yet.
        if self.status.state is not ConnectionState.RECONNECTING:
            self.status.state = ConnectionState.DEGRADED

    def _finalize_failure(self, err: Exception | None) -> None:
        # Distinguish "can't reach the lamp at all" from "reached but rejected".
        if isinstance(err, TransportError) and not self.transport.is_connected:
            self.status.state = ConnectionState.OFFLINE
        else:
            self.status.state = ConnectionState.ERROR

    # -- unreachable-duration notifications ----------------------------------

    def seconds_since_success(self, now: float | None = None) -> float | None:
        if self.status.last_success is None:
            return None
        return (now if now is not None else self._clock()) - self.status.last_success

    def poll_notification(self, now: float | None = None) -> NotificationEvent | None:
        """Return a due notification event, or None. Fires each threshold once.

        Escalating thresholds (2/10/30 min) fire at most once each per outage,
        preventing notification spam. Reset happens on the next success.
        """
        if self.status.state is ConnectionState.CONNECTED:
            return None
        elapsed = self.seconds_since_success(now)
        if elapsed is None:
            return None
        c = self.config
        for level, threshold in (
            ("critical", c.critical_after),
            ("warning", c.warning2_after),
            ("warning", c.warning_after),
        ):
            if elapsed >= threshold > self.status.highest_notification_sent:
                self.status.highest_notification_sent = threshold
                return NotificationEvent(level, elapsed, threshold)
        return None
