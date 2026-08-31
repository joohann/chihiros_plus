"""Sensor platform: connection, RSSI, program, phase, unreachable duration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CoordinatorData
from .entity import ChihirosEntity


@dataclass(frozen=True, kw_only=True)
class ChihirosSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoordinatorData], object]


SENSORS: tuple[ChihirosSensorDescription, ...] = (
    ChihirosSensorDescription(
        key="connection",
        translation_key="connection",
        icon="mdi:bluetooth",
        device_class=SensorDeviceClass.ENUM,
        options=["connected", "degraded", "reconnecting", "offline", "error", "unknown"],
        value_fn=lambda d: d.connection.value,
    ),
    ChihirosSensorDescription(
        key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.rssi,
    ),
    ChihirosSensorDescription(
        key="program",
        translation_key="program",
        icon="mdi:playlist-play",
        value_fn=lambda d: d.program_name,
    ),
    ChihirosSensorDescription(
        key="phase",
        translation_key="phase",
        icon="mdi:weather-sunset",
        value_fn=lambda d: d.phase.value,
    ),
    ChihirosSensorDescription(
        key="unreachable_for",
        translation_key="unreachable_for",
        icon="mdi:timer-alert",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            round(d.seconds_since_success)
            if d.connection.value != "connected" and d.seconds_since_success is not None
            else 0
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ChihirosSensor(coordinator, desc) for desc in SENSORS)


class ChihirosSensor(ChihirosEntity, SensorEntity):
    entity_description: ChihirosSensorDescription

    def __init__(self, coordinator, description: ChihirosSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = self._uid(description.key)

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
