"""Binary sensor: Bluetooth connectivity + command-confirmed status."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ChihirosEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [ChihirosConnectedBinarySensor(coordinator), ChihirosConfirmedBinarySensor(coordinator)]
    )


class ChihirosConnectedBinarySensor(ChihirosEntity, BinarySensorEntity):
    _attr_translation_key = "bluetooth_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = self._uid("bluetooth_connected")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.connection.value == "connected"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class ChihirosConfirmedBinarySensor(ChihirosEntity, BinarySensorEntity):
    """True only when the lamp acknowledged the last desired state.

    Off means the desired output is NOT confirmed — the integration never
    fabricates a confirmed state without an acknowledgement.
    """

    _attr_translation_key = "state_confirmed"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = self._uid("state_confirmed")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.is_confirmed

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
