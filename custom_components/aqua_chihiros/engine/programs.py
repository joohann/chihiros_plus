"""Program definitions for the Aquarium Light Engine.

A program is *only* a set of parameters. It contains no scheduling code and
no BLE — the single shared LightEngine turns these parameters into a full
day of light. Adding a new program means adding parameters here, nothing
else.

Presets are conservative starting points, not guarantees: a "Plant Growth"
program does not promise better plant growth, and "Algae Protection" is a
supporting measure, not a cure.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..protocol.models import RGBW


@dataclass(frozen=True, slots=True)
class MiddayPause:
    """An optional 'siesta' dip during the peak hold (helps limit algae)."""

    start_minute: int   # minutes from midnight
    duration_minutes: int
    intensity: int      # 0..100, brightness held during the pause


@dataclass(frozen=True, slots=True)
class ProgramParameters:
    """Everything the engine needs to simulate one day. Pure parameters."""

    name: str
    start_minute: int              # sunrise begins, minutes from midnight
    day_length_minutes: int        # start -> lights fully off
    sunrise_minutes: int
    sunset_minutes: int
    max_intensity: int             # 0..100
    peak_color: RGBW               # channel mix at full day
    moonlight_intensity: int = 0   # 0..100
    moonlight_minutes: int = 0
    moonlight_color: RGBW = RGBW(r=0, g=0, b=40, w=0)
    midday_pause: MiddayPause | None = None

    def with_overrides(self, **changes: object) -> "ProgramParameters":
        """Return a copy with fields replaced (used by the options/UI layer)."""
        return replace(self, **changes)  # type: ignore[arg-type]


def _hm(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


# --- Presets ----------------------------------------------------------------
# Each is parameters only. The same engine renders them all.

NATURAL_DAY = ProgramParameters(
    name="Natural Day",
    start_minute=_hm(8),
    day_length_minutes=8 * 60,
    sunrise_minutes=60,
    sunset_minutes=60,
    max_intensity=80,
    peak_color=RGBW(r=70, g=65, b=85, w=40),
    moonlight_intensity=5,
    moonlight_minutes=120,
    moonlight_color=RGBW(r=0, g=0, b=40, w=0),
)

PLANT_GROWTH = ProgramParameters(
    name="Plant Growth",
    start_minute=_hm(8),
    day_length_minutes=8 * 60,       # tighter photoperiod
    sunrise_minutes=45,
    sunset_minutes=45,
    max_intensity=95,
    peak_color=RGBW(r=90, g=70, b=80, w=60),
    moonlight_intensity=0,
    moonlight_minutes=0,
)

LOW_TECH = ProgramParameters(
    name="Low Tech",
    start_minute=_hm(9),
    day_length_minutes=7 * 60,
    sunrise_minutes=90,              # long, gentle ramps
    sunset_minutes=90,
    max_intensity=55,
    peak_color=RGBW(r=55, g=50, b=60, w=30),
    moonlight_intensity=3,
    moonlight_minutes=90,
)

HIGH_TECH = ProgramParameters(
    name="High Tech",
    start_minute=_hm(8),
    day_length_minutes=9 * 60,
    sunrise_minutes=40,
    sunset_minutes=40,
    max_intensity=100,               # configurable cap; user may lower
    peak_color=RGBW(r=95, g=80, b=90, w=70),
    moonlight_intensity=0,
    moonlight_minutes=0,
)

MOONLIGHT = ProgramParameters(
    name="Moonlight",
    start_minute=_hm(20),
    day_length_minutes=1,            # effectively no daytime
    sunrise_minutes=0,
    sunset_minutes=0,
    max_intensity=0,
    peak_color=RGBW(),
    moonlight_intensity=8,
    moonlight_minutes=4 * 60,        # always bounded — never all night
    moonlight_color=RGBW(r=2, g=4, b=30, w=0),
)

# Early-stage algae protection: short photoperiod, low max, optional siesta.
# Meant to be run temporarily (e.g. 7 days) then reverted to the previous
# program by the controller layer.
ALGAE_PROTECTION_EARLY = ProgramParameters(
    name="Algae Protection – Early Stage",
    start_minute=_hm(10),
    day_length_minutes=6 * 60,
    sunrise_minutes=45,
    sunset_minutes=45,
    max_intensity=45,
    peak_color=RGBW(r=45, g=45, b=50, w=25),
    moonlight_intensity=0,
    moonlight_minutes=0,
    midday_pause=MiddayPause(start_minute=_hm(13), duration_minutes=180, intensity=0),
)

PLANT_RECOVERY = ProgramParameters(
    name="Plant Recovery",
    start_minute=_hm(9),
    day_length_minutes=8 * 60,       # stable, consistent photoperiod
    sunrise_minutes=60,
    sunset_minutes=60,
    max_intensity=60,                # moderate, steady intensity
    peak_color=RGBW(r=60, g=55, b=60, w=35),
    moonlight_intensity=3,
    moonlight_minutes=60,
)

# Split photoperiod with a real midday break — an established way to limit algae
# and give CO2 a chance to recover. Morning + pause + evening block.
SIESTA = ProgramParameters(
    name="Siesta",
    start_minute=_hm(9),
    day_length_minutes=10 * 60,      # 09:00 -> 19:00, with a pause in the middle
    sunrise_minutes=45,
    sunset_minutes=45,
    max_intensity=75,
    peak_color=RGBW(r=70, g=60, b=75, w=40),
    moonlight_intensity=3,
    moonlight_minutes=90,
    midday_pause=MiddayPause(start_minute=_hm(13), duration_minutes=180, intensity=0),
)

# Away from home: a short, dim day — less algae and evaporation while plants tick
# over.
VACATION = ProgramParameters(
    name="Vacation",
    start_minute=_hm(10),
    day_length_minutes=6 * 60,
    sunrise_minutes=60,
    sunset_minutes=60,
    max_intensity=40,
    peak_color=RGBW(r=40, g=35, b=45, w=20),
    moonlight_intensity=0,
    moonlight_minutes=0,
)

# An overcast day: a gentle, low-intensity variation.
CLOUDY_DAY = ProgramParameters(
    name="Cloudy Day",
    start_minute=_hm(8),
    day_length_minutes=8 * 60,
    sunrise_minutes=75,              # soft, slow ramps
    sunset_minutes=75,
    max_intensity=45,
    peak_color=RGBW(r=40, g=45, b=55, w=25),   # slightly cooler/greyer
    moonlight_intensity=3,
    moonlight_minutes=60,
)

# Total darkness — a temporary treatment for algae / cyanobacteria outbreaks.
# Best run for a bounded number of days and then reverted (supporting measure,
# not a cure; it stresses plants).
BLACKOUT = ProgramParameters(
    name="Blackout",
    start_minute=0,
    day_length_minutes=1,
    sunrise_minutes=0,
    sunset_minutes=0,
    max_intensity=0,
    peak_color=RGBW(),
    moonlight_intensity=0,
    moonlight_minutes=0,
)

PRESETS: dict[str, ProgramParameters] = {
    "natural_day": NATURAL_DAY,
    "plant_growth": PLANT_GROWTH,
    "low_tech": LOW_TECH,
    "high_tech": HIGH_TECH,
    "siesta": SIESTA,
    "cloudy_day": CLOUDY_DAY,
    "plant_recovery": PLANT_RECOVERY,
    "moonlight": MOONLIGHT,
    "vacation": VACATION,
    "algae_protection_early": ALGAE_PROTECTION_EARLY,
    "blackout": BLACKOUT,
}
