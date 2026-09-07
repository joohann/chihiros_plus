"""The Aquarium Light Engine.

One generic engine turns *any* program's parameters into a full simulated
day of light. It is completely independent of Home Assistant and Bluetooth:
give it program parameters and a moment in time, and it returns the desired
light state at that moment.

    engine = LightEngine(NATURAL_DAY)
    state = engine.get_state(datetime.now())
    # -> LightState(phase=PEAK, brightness=80, r=70, g=65, b=85, w=40, ...)

Design rules honoured here:
  * No BLE, no HA imports.
  * Programs contribute parameters only; all timing/interpolation lives here.
  * Smooth ramps via interpolation, not fixed step tables.
  * Moonlight is always bounded by its window — a bug cannot leave the
    moonlight burning all night, because outside the window the engine
    returns NIGHT (everything off).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..protocol.models import RGBW
from .interpolation import sample_curve
from .phases import Phase
from .programs import ProgramParameters

_DAY = 1440  # minutes


@dataclass(frozen=True, slots=True)
class LightState:
    """The engine's answer for one moment. Channels/brightness are 0..100."""

    phase: Phase
    brightness: int
    r: int
    g: int
    b: int
    w: int
    next_phase: Phase
    next_transition_minute: int  # minute-of-day (0..1439) of the next anchor

    @property
    def rgbw(self) -> RGBW:
        return RGBW(self.r, self.g, self.b, self.w)


class LightEngine:
    """Computes desired light for one program. Cheap to construct; stateless."""

    def __init__(self, program: ProgramParameters) -> None:
        self.program = program
        self._compute_anchors()

    def _compute_anchors(self) -> None:
        p = self.program
        start = p.start_minute
        day_end = start + p.day_length_minutes
        peak_start = start + p.sunrise_minutes
        sunset_start = day_end - p.sunset_minutes
        # If ramps overlap (ramps longer than the day), collapse them to a
        # single midpoint so the curve stays monotonic and valid.
        if peak_start > sunset_start:
            peak_start = sunset_start = (start + day_end) // 2
        self._start = start
        self._peak_start = peak_start
        self._sunset_start = sunset_start
        self._day_end = day_end
        self._moon_start = day_end
        self._moon_end = day_end + p.moonlight_minutes

        # Piecewise-linear brightness curve across the daytime portion.
        curve: list[tuple[float, float]] = [
            (start, 0.0),
            (peak_start, p.max_intensity),
        ]
        pause = p.midday_pause
        if pause and start < pause.start_minute < day_end:
            pend = pause.start_minute + pause.duration_minutes
            ramp = min(15, max(1, pause.duration_minutes // 4))
            curve += [
                (pause.start_minute, p.max_intensity),
                (pause.start_minute + ramp, pause.intensity),
                (max(pause.start_minute + ramp, pend - ramp), pause.intensity),
                (pend, p.max_intensity),
            ]
        curve += [
            (sunset_start, p.max_intensity),
            (day_end, 0.0),
        ]
        # Keep strictly sorted by x for the sampler.
        self._curve = sorted(curve, key=lambda kf: kf[0])

    @property
    def light_on_minute(self) -> int:
        """Minute-of-day the lights start rising (for CO₂ timing etc.)."""
        return int(self._start % _DAY)

    @property
    def light_off_minute(self) -> int:
        """Minute-of-day the lights reach off."""
        return int(self._day_end % _DAY)

    def get_state(self, when: datetime) -> LightState:
        """Return the desired light state at ``when`` (naive local time used)."""
        minute = when.hour * 60 + when.minute + when.second / 60
        # Try today's cycle and the previous day's (for moonlight past midnight).
        for candidate in (minute, minute + _DAY):
            state = self._eval(candidate)
            if state is not None:
                return state
        return self._night_state()

    def _eval(self, m: float) -> LightState | None:
        p = self.program
        if not (self._start <= m < self._moon_end):
            return None

        # Moonlight window (bounded). The colour defines the hue mix; it is
        # scaled so the brightest channel equals moonlight_intensity, so a
        # 5% moonlight is genuinely dim regardless of the colour's raw values.
        if m >= self._moon_start:
            mc = p.moonlight_color
            peak = max(mc.as_tuple())
            if peak > 0:
                scale = p.moonlight_intensity / peak
                r, g, b, w = (round(c * scale) for c in mc.as_tuple())
            else:
                r = g = b = w = 0
            return LightState(
                phase=Phase.MOONLIGHT,
                brightness=p.moonlight_intensity,
                r=r,
                g=g,
                b=b,
                w=w,
                next_phase=Phase.NIGHT,
                next_transition_minute=int(self._moon_end % _DAY),
            )

        # Daytime: sample the brightness curve, scale the peak colour by it.
        brightness = round(sample_curve(self._curve, m))
        r, g, b, w = self._scaled_color(brightness)
        phase, next_phase, next_min = self._daytime_phase(m)
        return LightState(
            phase=phase,
            brightness=brightness,
            r=r,
            g=g,
            b=b,
            w=w,
            next_phase=next_phase,
            next_transition_minute=next_min,
        )

    def _scaled_color(self, brightness: int) -> tuple[int, int, int, int]:
        p = self.program
        if p.max_intensity <= 0:
            return (0, 0, 0, 0)
        scale = brightness / p.max_intensity
        pc = p.peak_color
        return (
            round(pc.r * scale),
            round(pc.g * scale),
            round(pc.b * scale),
            round(pc.w * scale),
        )

    def _daytime_phase(self, m: float) -> tuple[Phase, Phase, int]:
        if m < self._peak_start:
            return Phase.SUNRISE, Phase.PEAK, int(self._peak_start % _DAY)
        if m < self._sunset_start:
            return Phase.PEAK, Phase.SUNSET, int(self._sunset_start % _DAY)
        # sunset ramp down to day_end
        nxt = (
            (Phase.MOONLIGHT, self._moon_start)
            if self.program.moonlight_minutes > 0
            else (Phase.NIGHT, self._day_end)
        )
        return Phase.SUNSET, nxt[0], int(nxt[1] % _DAY)

    def _night_state(self) -> LightState:
        return LightState(
            phase=Phase.NIGHT,
            brightness=0,
            r=0,
            g=0,
            b=0,
            w=0,
            next_phase=Phase.SUNRISE,
            next_transition_minute=int(self._start % _DAY),
        )
