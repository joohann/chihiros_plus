"""Button platform: sync time, refresh, reconnect, emergency off."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ChihirosCoordinator
from .entity import ChihirosEntity


@dataclass(frozen=True, kw_only=True)
class ChihirosButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[ChihirosCoordinator], Awaitable[object]]


BUTTONS: tuple[ChihirosButtonDescription, ...] = (
    ChihirosButtonDescription(
        key="sync_time",
        translation_key="sync_time",
        icon="mdi:clock-check",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_sync_time(),
    ),
    ChihirosButtonDescription(
        key="refresh",
        translation_key="refresh",
        icon="mdi:refresh",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_request_refresh(),
    ),
    ChihirosButtonDescription(
        key="reconnect",
        translation_key="reconnect",
        icon="mdi:bluetooth-connect",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_reconnect(),
    ),
    ChihirosButtonDescription(
        key="maintenance",
        translation_key="maintenance",
        icon="mdi:broom",
        press_fn=lambda c: c.async_set_maintenance(True),
    ),
    ChihirosButtonDescription(
        key="emergency_off",
        translation_key="emergency_off",
        icon="mdi:flash-off",
        device_class=ButtonDeviceClass.RESTART,
        press_fn=lambda c: c.async_emergency_off(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ChihirosButton(coordinator, desc) for desc in BUTTONS)


class ChihirosButton(ChihirosEntity, ButtonEntity):
    entity_description: ChihirosButtonDescription

    def __init__(self, coordinator, description: ChihirosButtonDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = self._uid(description.key)

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
