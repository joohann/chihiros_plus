"""Chihiros aquarium lighting — standalone Home Assistant integration.

Local BLE only; there is no official Chihiros cloud API — "the protocol" here
is the reverse-engineered local Nordic-UART protocol, verified against real
WRGB II Slim hardware.

Home Assistant is imported *inside* the setup functions on purpose: importing
this package must not pull in Home Assistant, so the pure protocol/engine
layers under it stay importable and unit-testable without HA installed. HA is
always present when async_setup_entry actually runs.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

_LOGGER = logging.getLogger(__name__)

CONF_MODEL = "model"

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import ChihirosCoordinator

    type ChihirosConfigEntry = ConfigEntry[ChihirosCoordinator]


def sidebar_wanted(hass) -> bool:
    """The shared sidebar panel shows unless every entry has it switched off."""
    from .const import DOMAIN

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return True
    return any(e.options.get("sidebar", True) for e in entries)


def _platforms():
    from homeassistant.const import Platform

    return [
        Platform.LIGHT,
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.BUTTON,
    ]


async def async_setup_entry(hass: HomeAssistant, entry: ChihirosConfigEntry) -> bool:
    """Set up one lamp from a config entry."""
    from homeassistant.components import bluetooth
    from homeassistant.const import CONF_ADDRESS
    from homeassistant.core import callback
    from homeassistant.exceptions import ConfigEntryNotReady

    from .bluetooth import HAChihirosTransport
    from .coordinator import ChihirosCoordinator
    from .devices import get_model

    address: str = entry.data[CONF_ADDRESS]
    model = get_model(entry.data.get(CONF_MODEL, "wrgb_ii_slim"))
    if model is None:
        _LOGGER.error("Unknown Chihiros model for %s", entry.title)
        return False

    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(
            f"Chihiros lamp {address} not currently reachable via Bluetooth"
        )

    transport = HAChihirosTransport(ble_device, entry.title)
    coordinator = ChihirosCoordinator(hass, entry, transport, model)
    entry.runtime_data = coordinator

    @callback
    def _on_advertisement(service_info, change) -> None:
        # Keep the transport's BLEDevice/rssi fresh as advertisements arrive.
        transport.update_ble_device(service_info.device, service_info.rssi)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _on_advertisement,
            {"address": address, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, _platforms())

    # Websocket API + custom sidebar panel — registered once for the integration.
    from . import panel
    from .websocket import async_register as async_register_ws

    # Register websocket commands on every setup (idempotent — re-registering a
    # command type just overwrites its handler). NOT guarded by a one-shot flag,
    # so a reload after adding new commands actually registers them.
    async_register_ws(hass)
    if sidebar_wanted(hass):
        await panel.async_register_panel(hass)
    else:
        panel.async_remove_panel(hass)
    # NOTE: intentionally no options-update reload listener. Runtime settings
    # (program, schedule, follow-sun) are persisted via async_update_entry and
    # applied live by the coordinator; reloading on every option change would
    # tear the entry (and the BLE connection) down mid-request.
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChihirosConfigEntry) -> bool:
    """Unload a config entry and disconnect cleanly."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, _platforms())
    if unloaded:
        coordinator = entry.runtime_data
        await coordinator.transport.disconnect()

        from . import panel
        from .const import DOMAIN

        remaining = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining:
            panel.async_remove_panel(hass)
    return unloaded
