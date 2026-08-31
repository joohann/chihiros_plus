"""Light platform — the aquarium lamp as a native HA RGBW light.

Operating the light puts the lamp into manual mode (the program Select can put
it back on a program). Brightness/colour map to the four hardware channels
(0..100%). The light reports "on" from the desired state, but the connection
sensors carry the honest confirmed-vs-desired truth.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .engine import PRESETS
from .entity import ChihirosEntity
from .protocol import RGBW

_CHANNEL = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ChihirosLight(entry.runtime_data)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "apply_preset",
        {vol.Required("preset"): vol.In(list(PRESETS.keys()))},
        "async_service_apply_preset",
    )
    platform.async_register_entity_service(
        "set_rgbw",
        {
            vol.Required("red"): _CHANNEL,
            vol.Required("green"): _CHANNEL,
            vol.Required("blue"): _CHANNEL,
            vol.Required("white"): _CHANNEL,
        },
        "async_service_set_rgbw",
    )
    platform.async_register_entity_service(
        "start_algae_protection",
        {vol.Optional("days", default=7): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=60))},
        "async_service_start_algae_protection",
    )
    platform.async_register_entity_service("emergency_off", {}, "async_service_emergency_off")
    platform.async_register_entity_service("sync_time", {}, "async_service_sync_time")


def _pct_to_255(pct: int) -> int:
    return round(pct / 100 * 255)


def _255_to_pct(v: int) -> int:
    return round(v / 255 * 100)


class ChihirosLight(ChihirosEntity, LightEntity):
    _attr_name = None  # the light IS the device
    _attr_color_mode = ColorMode.RGBW
    _attr_supported_color_modes = {ColorMode.RGBW}

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = self._uid("light")

    @property
    def _desired(self) -> RGBW:
        return self.coordinator.data.desired

    @property
    def is_on(self) -> bool:
        return max(self._desired.as_tuple()) > 0

    @property
    def brightness(self) -> int | None:
        return _pct_to_255(max(self._desired.as_tuple()))

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        d = self._desired
        maxc = max(d.as_tuple())
        if maxc == 0:
            return (0, 0, 0, 0)
        # Normalise channels to the max so HA carries level in `brightness`.
        return tuple(round(c / maxc * 255) for c in d.as_tuple())  # type: ignore[return-value]

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgbw_in = kwargs.get(ATTR_RGBW_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        current = self._desired

        if rgbw_in is not None:
            base = [_255_to_pct(c) for c in rgbw_in]
        elif max(current.as_tuple()) > 0:
            base = list(current.as_tuple())
        else:
            base = [0, 0, 0, 100]  # turning on from off with no colour -> white

        if brightness is not None:
            # scale the colour so its brightest channel equals the requested level
            level_pct = _255_to_pct(brightness)
            peak = max(base) or 100
            base = [round(c / peak * level_pct) for c in base]

        await self.coordinator.async_set_manual_rgbw(RGBW(*[max(0, min(100, c)) for c in base]))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_manual_rgbw(RGBW(0, 0, 0, 0))

    # -- entity services -----------------------------------------------------

    async def async_service_apply_preset(self, preset: str) -> None:
        await self.coordinator.async_set_program(preset)

    async def async_service_set_rgbw(self, red: int, green: int, blue: int, white: int) -> None:
        await self.coordinator.async_set_manual_rgbw(RGBW(red, green, blue, white))

    async def async_service_start_algae_protection(self, days: float) -> None:
        await self.coordinator.async_start_temporary_program("algae_protection_early", days)

    async def async_service_emergency_off(self) -> None:
        await self.coordinator.async_emergency_off()

    async def async_service_sync_time(self) -> None:
        await self.coordinator.async_sync_time()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
