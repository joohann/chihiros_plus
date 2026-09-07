"""Number platform: manual per-channel control (R, G, B, W).

Setting a channel puts the lamp in manual mode and sends the updated RGBW.
These are a convenience alongside the light entity; the light and these
numbers stay in sync via the coordinator's desired state.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ChihirosEntity
from .protocol import RGBW


@dataclass(frozen=True, kw_only=True)
class ChannelNumberDescription(NumberEntityDescription):
    get_fn: Callable[[RGBW], int]
    field: str


CHANNELS: tuple[ChannelNumberDescription, ...] = (
    ChannelNumberDescription(key="red", translation_key="red", icon="mdi:palette",
                             field="r", get_fn=lambda c: c.r),
    ChannelNumberDescription(key="green", translation_key="green", icon="mdi:palette",
                             field="g", get_fn=lambda c: c.g),
    ChannelNumberDescription(key="blue", translation_key="blue", icon="mdi:palette",
                             field="b", get_fn=lambda c: c.b),
    ChannelNumberDescription(key="white", translation_key="white", icon="mdi:palette",
                             field="w", get_fn=lambda c: c.w),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ChihirosChannelNumber(coordinator, desc) for desc in CHANNELS)


class ChihirosChannelNumber(ChihirosEntity, NumberEntity):
    entity_description: ChannelNumberDescription
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, description: ChannelNumberDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = self._uid(f"channel_{description.key}")

    @property
    def native_value(self) -> float:
        return self.entity_description.get_fn(self.coordinator.data.desired)

    async def async_set_native_value(self, value: float) -> None:
        current = self.coordinator.data.desired
        updated = replace(current, **{self.entity_description.field: int(value)})
        await self.coordinator.async_set_manual_rgbw(updated)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
