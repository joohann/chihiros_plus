"""Light Controller — the abstraction between the engine and one physical lamp.

Responsibilities:
  * Translate a desired RGBW (from the Aquarium Light Engine, at group level)
    into per-lamp output, applying an optional per-lamp calibration.
  * Send it through the Watchdog, so every command gets the retry/reconnect
    ladder for free.
  * Track ``desired`` vs ``confirmed`` honestly: ``confirmed`` is set only when
    the link acknowledged the command; it is ``None`` (UNKNOWN) otherwise.
  * Avoid redundant BLE traffic via state-change detection — an unchanged,
    already-confirmed target is not re-sent.

Knows nothing about Home Assistant. Depends on the protocol commands and the
watchdog/transport interface only. The engine stays above it and never touches
BLE; this controller never computes a light curve.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .protocol import (
    RGBW,
    MessageIdCounter,
    enter_auto_mode,
    enter_manual_mode,
    set_rgbw,
    set_time,
)
from .watchdog import Watchdog


@dataclass(frozen=True, slots=True)
class Calibration:
    """Per-lamp correction so two lamps on one tank can be matched."""

    scale_r: float = 1.0
    scale_g: float = 1.0
    scale_b: float = 1.0
    scale_w: float = 1.0

    def apply(self, color: RGBW) -> RGBW:
        def clamp(value: float) -> int:
            return max(0, min(100, round(value)))

        return RGBW(
            clamp(color.r * self.scale_r),
            clamp(color.g * self.scale_g),
            clamp(color.b * self.scale_b),
            clamp(color.w * self.scale_w),
        )


class LightController:
    """Drives one lamp. Construct one per physical device."""

    def __init__(
        self,
        name: str,
        watchdog: Watchdog,
        *,
        calibration: Calibration | None = None,
        msg_id: MessageIdCounter | None = None,
    ) -> None:
        self.name = name
        self.watchdog = watchdog
        self.calibration = calibration or Calibration()
        self._msg_id = msg_id or MessageIdCounter()
        self.desired: RGBW | None = None       # device-level target we intend
        self.confirmed: RGBW | None = None      # None == UNKNOWN (unacknowledged)
        self._last_sent: RGBW | None = None

    @property
    def is_confirmed(self) -> bool:
        """True only when the last intended target was acknowledged by the lamp."""
        return self.confirmed is not None and self.confirmed == self.desired

    async def apply_rgbw(self, color: RGBW, *, force: bool = False) -> bool:
        """Send a calibrated RGBW to the lamp. Returns True if confirmed.

        Skips the write when the calibrated target is unchanged and already
        confirmed, unless ``force`` is set (used by emergency off).
        """
        target = self.calibration.apply(color)
        self.desired = target
        if not force and target == self._last_sent and self.confirmed == target:
            return True
        # Always assert manual mode before writing channels, otherwise the
        # lamp's own internal schedule (if active) overrides our output — the
        # classic "it won't turn off" symptom. enter_manual is idempotent and
        # only sent when we actually push a change (steady state is deduped).
        frames = [enter_manual_mode(self._msg_id), *set_rgbw(target, self._msg_id)]
        ok = await self.watchdog.execute(frames)
        self._last_sent = target
        self.confirmed = target if ok else None  # UNKNOWN on any failure
        return ok

    async def emergency_off(self) -> bool:
        """Best-effort immediate off. Forces a write even if we think it's off.

        A BLE device cannot be turned off when no link is possible at all; this
        returns False in that case and the caller must surface that clearly.
        """
        return await self.apply_rgbw(RGBW(0, 0, 0, 0), force=True)

    async def enter_manual(self) -> bool:
        return await self.watchdog.execute([enter_manual_mode(self._msg_id)])

    async def enter_auto(self) -> bool:
        """Switch the lamp to its on-device schedule (hardware fail-safe)."""
        return await self.watchdog.execute([enter_auto_mode(self._msg_id)])

    async def sync_time(self, now: datetime) -> bool:
        """Push Home Assistant's local time to the lamp's internal clock.

        ISO weekday (1=Mon..7=Sun) is used, matching the protocol.
        """
        frame = set_time(
            year=now.year,
            month=now.month,
            weekday=now.isoweekday(),
            hour=now.hour,
            minute=now.minute,
            second=now.second,
            msg_id=self._msg_id,
        )
        return await self.watchdog.execute([frame])
