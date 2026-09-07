"""Select platform: choose the active lighting program."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .engine import PRESETS
from .entity import ChihirosEntity

# Stable option order for the UI.
_OPTIONS = list(PRESETS.keys())


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ChihirosProgramSelect(entry.runtime_data)])


class ChihirosProgramSelect(ChihirosEntity, SelectEntity):
    _attr_translation_key = "program"
    _attr_icon = "mdi:playlist-play"
    _attr_options = _OPTIONS

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = self._uid("program_select")

    @property
    def current_option(self) -> str | None:
        key = self.coordinator.program_key
        return key if key in _OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_program(option)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
