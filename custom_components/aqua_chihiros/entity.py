"""Shared base entity: device info + coordinator wiring.

All Chihiros entities attach to one HA device (the lamp) and read their state
from the coordinator snapshot. Entities never compute light values or touch
BLE — they render coordinator data and call coordinator methods.
"""
from __future__ import annotations

from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ChihirosCoordinator


class ChihirosEntity(CoordinatorEntity[ChihirosCoordinator]):
    """Base for all Chihiros entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ChihirosCoordinator) -> None:
        super().__init__(coordinator)
        address = coordinator.entry.data[CONF_ADDRESS]
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            manufacturer="Chihiros",
            model=coordinator.model.name,
            name=coordinator.entry.title,
        )

    @property
    def _address(self) -> str:
        return self.coordinator.entry.data[CONF_ADDRESS]

    def _uid(self, suffix: str) -> str:
        return f"{self.coordinator.entry.entry_id}_{suffix}"
