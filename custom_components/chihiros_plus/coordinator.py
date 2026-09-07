"""Runtime coordinator: binds the engine, controller and watchdog for one lamp.

One coordinator per config entry (one lamp). It periodically asks the Aquarium
Light Engine for the desired state and pushes it through the Light Controller
(which routes via the Watchdog). Manual control and program switching go
through the same single path — no per-program scheduler, no BLE logic here.

The engine computes desired state even while offline; the controller reports
``confirmed`` only when the lamp acknowledged, so entities can show the honest
desired-vs-confirmed difference. This module is the boundary where Home
Assistant meets the pure layers; the layers below it never import HA.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .controller import Calibration, LightController
from .devices import ChihirosModel
from .engine import PRESETS, LightEngine, LightState, Phase, ProgramParameters
from .engine.programs import NATURAL_DAY
from .protocol import RGBW
from .transport import Transport
from .watchdog import ConnectionState, Watchdog, WatchdogConfig

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=30)

# Default aquarium photoperiod when following the sun and the user hasn't set a
# day length. A real sunrise→sunset day (13–16 h in summer) is far too long for
# an aquarium and promotes algae; 6–8 h is the usual recommendation, so we
# default to a conservative 8 h ending at the real sunset.
DEFAULT_PHOTOPERIOD_MINUTES = 8 * 60

MODE_PROGRAM = "program"
MODE_MANUAL = "manual"
MODE_OFF = "off"


@dataclass(slots=True)
class CoordinatorData:
    """Snapshot entities render from. All values are honest, never fabricated."""

    mode: str
    program_key: str
    program_name: str
    phase: Phase
    desired: RGBW
    confirmed: RGBW | None       # None == UNKNOWN (unacknowledged)
    brightness: int
    connection: ConnectionState
    rssi: int | None
    seconds_since_success: float | None
    is_confirmed: bool


class ChihirosCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Drives one lamp on an interval, and on demand."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        transport: Transport,
        model: ChihirosModel,
        *,
        calibration: Calibration | None = None,
        watchdog_config: WatchdogConfig | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}:{entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.model = model
        self.transport = transport
        self.watchdog = Watchdog(transport, watchdog_config or WatchdogConfig())
        self.controller = LightController(
            entry.title, self.watchdog, calibration=calibration
        )
        # Restore the last selected program from the entry options so a reload
        # or restart keeps it (BLE can't read the program back from the lamp).
        self._program_key = entry.options.get("program", "natural_day")
        # User overrides (start_minute / day_length_minutes) applied on top of
        # whichever preset is selected; persisted in the config entry options.
        self._overrides: dict[str, int] = dict(entry.options.get("overrides", {}))
        # Follow the real local sunrise/sunset by default; manual start/length
        # edits switch this off ("deviate"). Persisted in the entry options.
        self._follow_sun: bool = bool(entry.options.get("follow_sun", True))
        self._program: ProgramParameters = NATURAL_DAY
        self._rebuild_engine()
        self._previous_program_key: str | None = None
        self._mode = MODE_PROGRAM
        self._manual = RGBW(0, 0, 0, 0)
        self._revert_cancel = None
        self._apply_task = None
        self._identifying = False       # true while blinking for identify
        self._maintenance = False
        self._pending: tuple[Phase, RGBW] = (Phase.NIGHT, RGBW(0, 0, 0, 0))
        # Active timed treatment (Blackout / Algae Protection for N days), if
        # any. Persisted in options so it survives restarts.
        self._treatment: dict | None = entry.options.get("treatment")
        if self._treatment:
            self._restore_treatment()
        # Optional CO₂ coupling: a user-chosen switch driven ON before lights on
        # and OFF before lights off, following the active program's photoperiod.
        self._co2_switch: str | None = entry.options.get("co2_switch")
        self._co2_before_on: int = int(entry.options.get("co2_before_on", 60))
        self._co2_before_off: int = int(entry.options.get("co2_before_off", 60))

    # -- program / mode control ---------------------------------------------

    @property
    def program_key(self) -> str:
        return self._program_key

    @property
    def mode(self) -> str:
        return self._mode

    def _sun_times(self) -> dict[str, int] | None:
        """Today's real sunrise/sunset in local minutes, or None if unavailable."""
        from homeassistant.helpers.sun import get_astral_event_date

        today = dt_util.now().date()
        rise = get_astral_event_date(self.hass, "sunrise", today)
        set_ = get_astral_event_date(self.hass, "sunset", today)
        if rise is None or set_ is None:
            return None
        rise = dt_util.as_local(rise)
        set_ = dt_util.as_local(set_)
        return {
            "sunrise": rise.hour * 60 + rise.minute,
            "sunset": set_.hour * 60 + set_.minute,
        }

    def _apply_overrides(self, program: ProgramParameters) -> ProgramParameters:
        if self._follow_sun:
            sun = self._sun_times()
            if sun is not None:
                # Anchor the END to the real sunset; the day length is the
                # user's if set (adjust from the front), else the natural
                # sunrise->sunset span. Start = sunset - length.
                length = self._overrides.get("day_length_minutes") or DEFAULT_PHOTOPERIOD_MINUTES
                length = max(1, min(1440, int(length)))
                start = sun["sunset"] - length
                if start < 0:
                    start += 1440
                return program.with_overrides(
                    start_minute=start % 1440, day_length_minutes=length
                )
            # fall through to manual/preset if the sun schedule is unavailable
        ov = {k: v for k, v in self._overrides.items() if v is not None}
        return program.with_overrides(**ov) if ov else program

    def _rebuild_engine(self) -> None:
        base = PRESETS.get(self._program_key, NATURAL_DAY)
        self._program = self._apply_overrides(base)
        self._engine = LightEngine(self._program)

    async def async_set_program(self, key: str) -> None:
        if key not in PRESETS:
            raise ValueError(f"unknown program '{key}'")
        self._cancel_revert()
        self._treatment = None          # a manual program choice ends any treatment
        self._maintenance = False
        self._program_key = key
        self._rebuild_engine()
        self._mode = MODE_PROGRAM
        opts = {**self.entry.options, "program": key}
        opts.pop("treatment", None)
        self.hass.config_entries.async_update_entry(self.entry, options=opts)
        await self.async_request_refresh()

    async def async_set_schedule(
        self, start_minute: int | None, day_length_minutes: int | None
    ) -> None:
        """Set start time / day length overrides and persist them.

        Applied on top of the current program so the same override follows the
        user across preset changes. Persisted to the config entry options so it
        survives restarts.
        """
        if start_minute is not None:
            self._overrides["start_minute"] = max(0, min(1439, int(start_minute)))
            # Setting an explicit start means fully manual (stop following sun).
            self._follow_sun = False
        if day_length_minutes is not None:
            self._overrides["day_length_minutes"] = max(1, min(1440, int(day_length_minutes)))
            # Day length is honoured in BOTH modes: in follow-sun it adjusts the
            # start (front) while the sunset stays anchored to the real sun.
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={
                **self.entry.options,
                "overrides": self._overrides,
                "follow_sun": self._follow_sun,
            },
        )
        self._rebuild_engine()
        self._mode = MODE_PROGRAM
        await self.async_request_refresh()

    async def async_set_tank(self, name: str | None) -> None:
        """Assign this lamp to a tank/aquarium group (or clear it)."""
        name = (name or "").strip()
        opts = {**self.entry.options}
        if name:
            opts["tank"] = name
        else:
            opts.pop("tank", None)
        self.hass.config_entries.async_update_entry(self.entry, options=opts)
        await self.async_request_refresh()

    async def async_complete_onboarding(self) -> None:
        """Mark first-time setup as finished so the panel shows the controls."""
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, "onboarded": True}
        )
        await self.async_request_refresh()

    async def async_set_follow_sun(self, enabled: bool) -> None:
        """Toggle following the real sunrise/sunset."""
        self._follow_sun = bool(enabled)
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, "follow_sun": self._follow_sun},
        )
        self._rebuild_engine()
        self._mode = MODE_PROGRAM
        await self.async_request_refresh()

    async def async_apply_custom_program(
        self, key: str, program: ProgramParameters
    ) -> None:
        """Apply a program built from user parameters (options/UI/services)."""
        self._cancel_revert()
        self._program_key = key
        self._program = program
        self._engine = LightEngine(program)
        self._mode = MODE_PROGRAM
        await self.async_request_refresh()

    async def async_start_temporary_program(self, key: str, days: float) -> None:
        """Run a program as a timed treatment, then auto-revert.

        Used by Blackout / Algae Protection: activate for N days then
        automatically restore the program that was active before. The treatment
        (program, start time, duration, revert target) is persisted in the entry
        options, so the countdown and auto-revert survive a restart.
        """
        if key not in PRESETS:
            raise ValueError(f"unknown program '{key}'")
        revert_to = (
            self._treatment["revert_to"]
            if self._treatment
            else (self._program_key if self._mode == MODE_PROGRAM else "natural_day")
        )
        self._treatment = {
            "program": key,
            "started": dt_util.utcnow().isoformat(),
            "days": float(days),
            "revert_to": revert_to,
        }
        self._maintenance = False
        self._program_key = key
        self._rebuild_engine()
        self._mode = MODE_PROGRAM
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, "program": key, "treatment": self._treatment},
        )
        self._schedule_revert(days * 86400)
        await self.async_request_refresh()

    def _schedule_revert(self, seconds: float) -> None:
        self._cancel_revert()

        @callback
        def _revert(_now) -> None:
            self._revert_cancel = None
            self.hass.async_create_task(self.async_stop_treatment())

        self._revert_cancel = async_call_later(self.hass, max(1.0, seconds), _revert)

    def _restore_treatment(self) -> None:
        """After a restart, resume the countdown (or revert if already over)."""
        started = dt_util.parse_datetime(self._treatment.get("started", ""))
        if started is None:
            self._treatment = None
            return
        remaining = self._treatment["days"] * 86400 - (
            dt_util.utcnow() - started
        ).total_seconds()
        self._program_key = self._treatment["program"]
        if remaining <= 0:
            self.hass.async_create_task(self.async_stop_treatment())
        else:
            self._schedule_revert(remaining)

    async def async_stop_treatment(self) -> None:
        """End the treatment now and revert to the remembered program."""
        if not self._treatment:
            return
        revert_to = self._treatment.get("revert_to", "natural_day")
        self._treatment = None
        self._cancel_revert()
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={k: v for k, v in self.entry.options.items() if k != "treatment"},
        )
        await self.async_set_program(revert_to if revert_to in PRESETS else "natural_day")

    def _cancel_revert(self) -> None:
        if self._revert_cancel is not None:
            self._revert_cancel()
            self._revert_cancel = None

    async def async_set_maintenance(self, enable: bool) -> None:
        """Interrupt the program with full white for cleaning, or resume it."""
        if enable:
            self._cancel_revert()
            self._maintenance = True
            self._manual = RGBW(100, 100, 100, 100)  # full bright white
            self._mode = MODE_MANUAL
            await self.async_request_refresh()
        else:
            self._maintenance = False
            await self.async_set_program(self._program_key)  # back to the program

    async def async_set_manual_rgbw(self, color: RGBW) -> None:
        self._cancel_revert()
        self._maintenance = False
        self._manual = color
        self._mode = MODE_OFF if color == RGBW(0, 0, 0, 0) else MODE_MANUAL
        await self.async_request_refresh()

    async def async_emergency_off(self) -> bool:
        self._cancel_revert()
        self._maintenance = False
        self._mode = MODE_OFF
        self._manual = RGBW(0, 0, 0, 0)
        ok = await self.controller.emergency_off()
        await self.async_request_refresh()
        return ok

    async def async_identify(self, cycles: int = 4) -> bool:
        """Blink the lamp a few times so the user can spot which physical unit
        this entry is, then restore the normal output. Uses full brightness on
        every channel and forces both states so nothing is deduped/skipped, and
        pauses the background apply loop so it can't overwrite the blink."""
        self._identifying = True
        ok = True
        full, dark = RGBW(100, 100, 100, 100), RGBW(0, 0, 0, 0)
        try:
            for _ in range(max(1, cycles)):
                ok = await self.controller.apply_rgbw(full, force=True) and ok
                await asyncio.sleep(0.55)
                await self.controller.apply_rgbw(dark, force=True)
                await asyncio.sleep(0.55)
        finally:
            self._identifying = False
        await self.async_request_refresh()   # back to the real desired output
        return ok

    async def async_sync_time(self) -> bool:
        return await self.controller.sync_time(dt_util.now())

    async def async_reconnect(self) -> bool:
        await self.transport.disconnect()
        return await self.watchdog.execute([])  # empty -> just (re)connect

    # -- the single apply path ----------------------------------------------

    def _desired_state(self) -> tuple[Phase, RGBW]:
        if self._mode == MODE_PROGRAM:
            state: LightState = self._engine.get_state(dt_util.now())
            return state.phase, state.rgbw
        # manual / off: hold the user's colour, no phase from the engine
        return Phase.NIGHT if self._mode == MODE_OFF else Phase.PEAK, self._manual

    async def _async_update_data(self) -> CoordinatorData:
        """Return a snapshot immediately; do BLE work in the background.

        This MUST NOT await BLE I/O: async_config_entry_first_refresh() calls
        it during setup, and a slow connect here would block the whole entry
        from finishing (the "stuck Initialising" bug). The actual write runs in
        a background task and pushes a fresh snapshot when it completes.
        """
        # When following the sun, refresh the schedule each tick so it tracks
        # today's real sunrise/sunset (and drifts with the seasons). Cheap.
        if self._mode == MODE_PROGRAM and self._follow_sun:
            self._rebuild_engine()
        phase, desired = self._desired_state()
        self._pending = (phase, desired)
        self._schedule_apply()
        return self._build_snapshot(phase, desired)

    def _schedule_apply(self) -> None:
        if self._identifying:
            return  # don't fight the identify blink; it restores state when done
        if self._apply_task is not None and not self._apply_task.done():
            return  # one apply in flight; it will pick up the latest _pending
        self._apply_task = self.hass.async_create_background_task(
            self._run_apply(), name=f"{self.name}_apply"
        )

    async def _run_apply(self) -> None:
        phase, desired = self._pending
        try:
            await self.controller.apply_rgbw(desired)
        except Exception:  # pragma: no cover - watchdog already handles retries
            _LOGGER.debug("%s: apply failed", self.name, exc_info=True)
        try:
            await self._apply_co2()
        except Exception:  # pragma: no cover - never let CO₂ break the update
            _LOGGER.debug("%s: CO2 apply failed", self.name, exc_info=True)
        event = self.watchdog.poll_notification()
        if event is not None:
            self._notify_unreachable(event.level, event.elapsed_seconds)
        # Push the post-apply state (now with confirmation) to entities without
        # re-entering the update loop.
        self.async_set_updated_data(self._build_snapshot(phase, desired))

    def _build_snapshot(self, phase: Phase, desired: RGBW) -> CoordinatorData:
        st = self.watchdog.status
        return CoordinatorData(
            mode=self._mode,
            program_key=self._program_key,
            program_name=self._program.name,
            phase=phase,
            desired=self.controller.desired or desired,
            confirmed=self.controller.confirmed,
            brightness=max(desired.as_tuple()),
            connection=st.state,
            rssi=st.rssi,
            seconds_since_success=self.watchdog.seconds_since_success(),
            is_confirmed=self.controller.is_confirmed,
        )

    # -- serialisation for the custom panel / websocket API -----------------

    @callback
    def snapshot(self) -> dict:
        """A JSON-serialisable view of this lamp for the panel."""
        d = self.data
        return {
            "entry_id": self.entry.entry_id,
            "name": self.entry.title,
            # Tank/aquarium group: lamps sharing a tank name are controlled
            # together by the panel. Unset -> the lamp is its own tank.
            "tank": self.entry.options.get("tank") or self.entry.title,
            # First-time setup: freshly added lamps (options set by the config
            # flow) start False so the panel offers a wizard. Existing entries
            # have no such key -> treated as already onboarded.
            "onboarded": bool(self.entry.options.get("onboarded", True)),
            "model": self.model.name,
            "mode": d.mode,
            "program_key": d.program_key,
            "program_name": d.program_name,
            "phase": d.phase.value,
            "brightness": d.brightness,
            "start_minute": self._program.start_minute,
            "day_length_minutes": self._program.day_length_minutes,
            "follow_sun": self._follow_sun,
            "maintenance": self._maintenance,
            "treatment": self._treatment_snapshot(),
            "co2": self._co2_snapshot(),
            "desired": list(d.desired.as_tuple()),
            "confirmed": list(d.confirmed.as_tuple()) if d.confirmed else None,
            "is_confirmed": d.is_confirmed,
            "connection": d.connection.value,
            "rssi": d.rssi,
            "seconds_since_success": d.seconds_since_success,
        }

    @callback
    def _treatment_snapshot(self) -> dict | None:
        """Timed-treatment status for the panel: which day of how many."""
        if not self._treatment:
            return None
        started = dt_util.parse_datetime(self._treatment.get("started", ""))
        total = float(self._treatment["days"])
        elapsed_days = (
            (dt_util.utcnow() - started).total_seconds() / 86400 if started else 0.0
        )
        program = PRESETS.get(self._treatment["program"])
        revert = PRESETS.get(self._treatment.get("revert_to", "natural_day"), NATURAL_DAY)
        return {
            "name": program.name if program else self._treatment["program"],
            "day": min(int(total) if total >= 1 else 1, int(elapsed_days) + 1),
            "total_days": total,
            "revert_to": revert.name,
            "progress": max(0.0, min(1.0, elapsed_days / total)) if total else 1.0,
        }

    # -- optional CO₂ coupling ----------------------------------------------

    def _co2_window(self) -> tuple[int, int] | None:
        """(on, off) minute-of-day for CO₂, or None if it must not run now."""
        if self._mode != MODE_PROGRAM:
            return None
        p = self._program
        if p.max_intensity <= 0 or p.day_length_minutes < 60:
            return None  # Blackout / Moonlight: no real photoperiod
        on = (self._engine.light_on_minute - self._co2_before_on) % 1440
        off = (self._engine.light_off_minute - self._co2_before_off) % 1440
        return on, off

    @staticmethod
    def _in_window(now: int, start: int, end: int) -> bool:
        if start == end:
            return False
        return start <= now < end if start < end else (now >= start or now < end)

    def _co2_desired(self) -> bool | None:
        if not self._co2_switch:
            return None
        window = self._co2_window()
        if window is None:
            return False
        now = dt_util.now()
        return self._in_window(now.hour * 60 + now.minute, *window)

    async def _apply_co2(self) -> None:
        want = self._co2_desired()
        if want is None:
            return
        state = self.hass.states.get(self._co2_switch)
        if state is None:
            return  # entity gone/unavailable — don't guess
        is_on = state.state == "on"
        service = "turn_on" if want and not is_on else "turn_off" if not want and is_on else None
        if service:
            await self.hass.services.async_call(
                "homeassistant", service, {"entity_id": self._co2_switch}, blocking=False)

    async def async_set_co2(self, switch, before_on, before_off) -> None:
        self._co2_switch = switch or None
        self._co2_before_on = max(0, min(360, int(before_on)))
        self._co2_before_off = max(0, min(360, int(before_off)))
        opts = {
            **self.entry.options,
            "co2_before_on": self._co2_before_on,
            "co2_before_off": self._co2_before_off,
        }
        if self._co2_switch:
            opts["co2_switch"] = self._co2_switch
        else:
            opts.pop("co2_switch", None)
        self.hass.config_entries.async_update_entry(self.entry, options=opts)
        await self.async_request_refresh()

    @callback
    def _co2_snapshot(self) -> dict:
        window = self._co2_window() if self._co2_switch else None
        fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"  # noqa: E731
        return {
            "enabled": bool(self._co2_switch),
            "switch": self._co2_switch,
            "before_on": self._co2_before_on,
            "before_off": self._co2_before_off,
            "on": self._co2_desired(),
            "on_at": fmt(window[0]) if window else None,
            "off_at": fmt(window[1]) if window else None,
        }

    @callback
    def sample_day(self, step_minutes: int = 15) -> dict:
        """Sample the current program across 24h for the panel's curve.

        Uses the engine directly (pure computation) — this reflects the
        program even while the lamp is offline.
        """
        from datetime import datetime, time

        base = dt_util.now().replace(second=0, microsecond=0)
        points = []
        for minute in range(0, 1440, step_minutes):
            dt = datetime.combine(base.date(), time(minute // 60, minute % 60), base.tzinfo)
            st = self._engine.get_state(dt)
            points.append(
                {"m": minute, "b": st.brightness, "rgbw": [st.r, st.g, st.b, st.w]}
            )
        now = dt_util.now()
        return {
            "program_key": self._program_key,
            "program_name": self._program.name,
            "now_minute": now.hour * 60 + now.minute,
            "points": points,
        }

    @callback
    def _notify_unreachable(self, level: str, elapsed: float) -> None:
        minutes = int(elapsed // 60)
        prefix = "CRITICAL: " if level == "critical" else ""
        persistent_notification.async_create(
            self.hass,
            f"{prefix}{self.entry.title} Bluetooth unreachable for {minutes} min.",
            title="Chihiros aquarium light",
            notification_id=f"{DOMAIN}_{self.entry.entry_id}_unreachable",
        )
