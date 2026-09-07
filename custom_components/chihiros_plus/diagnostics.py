"""Diagnostics: a full, honest snapshot for troubleshooting."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import ChihirosCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry
) -> dict[str, Any]:
    coordinator: ChihirosCoordinator = entry.runtime_data
    data = coordinator.data
    status = coordinator.watchdog.status
    return {
        "model": coordinator.model.name,
        "address": entry.data.get("address"),
        "mode": coordinator.mode,
        "program": {"key": data.program_key, "name": data.program_name, "phase": data.phase.value},
        "light": {
            "desired": data.desired.as_tuple(),
            "confirmed": data.confirmed.as_tuple() if data.confirmed else None,
            "is_confirmed": data.is_confirmed,
            "brightness": data.brightness,
        },
        "connection": {
            "state": status.state.value,
            "rssi": status.rssi,
            "retry_count": status.retry_count,
            "consecutive_failures": status.consecutive_failures,
            "last_error": status.last_error,
            "seconds_since_success": data.seconds_since_success,
        },
        "watchdog_config": {
            "max_retries": coordinator.watchdog.config.max_retries,
            "retry_interval": coordinator.watchdog.config.retry_interval,
        },
    }
