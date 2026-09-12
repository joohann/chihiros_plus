"""Websocket API — the custom panel talks to the backend through this.

A custom panel (frontend/chihiros-panel.js) has no direct access to config
entries, so all its reads and actions go through these commands, the same
pattern the Nida and NL-Alert panels use. Commands are registered once for
the integration.

Nothing here computes light values — it delegates to the coordinators, which
own the engine/controller. The panel is a view, not a second scheduler.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .coordinator import ChihirosCoordinator
from .protocol import RGBW


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list_devices)
    websocket_api.async_register_command(hass, ws_get_curve)
    websocket_api.async_register_command(hass, ws_set_program)
    websocket_api.async_register_command(hass, ws_set_schedule)
    websocket_api.async_register_command(hass, ws_set_follow_sun)
    websocket_api.async_register_command(hass, ws_set_moonlight)
    websocket_api.async_register_command(hass, ws_set_sidebar)
    websocket_api.async_register_command(hass, ws_set_maintenance)
    websocket_api.async_register_command(hass, ws_set_tank)
    websocket_api.async_register_command(hass, ws_complete_onboarding)
    websocket_api.async_register_command(hass, ws_start_treatment)
    websocket_api.async_register_command(hass, ws_stop_treatment)
    websocket_api.async_register_command(hass, ws_list_switches)
    websocket_api.async_register_command(hass, ws_set_co2)
    websocket_api.async_register_command(hass, ws_set_rgbw)
    websocket_api.async_register_command(hass, ws_emergency_off)
    websocket_api.async_register_command(hass, ws_reconnect)
    websocket_api.async_register_command(hass, ws_identify)


def _coordinators(hass: HomeAssistant) -> list[ChihirosCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


def _coordinator(hass: HomeAssistant, entry_id: str) -> ChihirosCoordinator | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or getattr(entry, "runtime_data", None) is None:
        return None
    return entry.runtime_data


@websocket_api.websocket_command({vol.Required("type"): "chihiros_plus/list_devices"})
@callback
def ws_list_devices(hass, connection, msg: dict[str, Any]) -> None:
    connection.send_result(
        msg["id"], {"devices": [c.snapshot() for c in _coordinators(hass)]}
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "chihiros_plus/get_curve", vol.Required("entry_id"): str}
)
@callback
def ws_get_curve(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    connection.send_result(msg["id"], coordinator.sample_day())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_program",
        vol.Required("entry_id"): str,
        vol.Required("program"): str,
    }
)
@websocket_api.async_response
async def ws_set_program(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    try:
        await coordinator.async_set_program(msg["program"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_program", str(err))
        return
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_schedule",
        vol.Required("entry_id"): str,
        vol.Optional("start_minute"): vol.All(int, vol.Range(min=0, max=1439)),
        vol.Optional("day_length_minutes"): vol.All(int, vol.Range(min=1, max=1440)),
    }
)
@websocket_api.async_response
async def ws_set_schedule(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_set_schedule(
        msg.get("start_minute"), msg.get("day_length_minutes")
    )
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_follow_sun",
        vol.Required("entry_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_set_follow_sun(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_set_follow_sun(msg["enabled"])
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_sidebar",
        vol.Required("entry_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_set_sidebar(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    # One shared panel: apply the choice to every entry, then add/remove it.
    for c in _coordinators(hass):
        await c.async_set_sidebar(msg["enabled"])
    from . import panel, sidebar_wanted

    if sidebar_wanted(hass):
        await panel.async_register_panel(hass)
    else:
        panel.async_remove_panel(hass)
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_moonlight",
        vol.Required("entry_id"): str,
        vol.Required("enabled"): bool,
        vol.Optional("mode"): vol.In(["all_night", "duration", "time", "switch"]),
        vol.Optional("hours"): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=12)),
        vol.Optional("off_minute"): vol.All(int, vol.Range(min=0, max=1439)),
        vol.Optional("switch"): vol.Any(None, str),
        vol.Optional("invert"): bool,
    }
)
@websocket_api.async_response
async def ws_set_moonlight(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_set_moonlight(
        msg["enabled"], msg.get("mode"), msg.get("hours"),
        msg.get("off_minute"), msg.get("switch"), msg.get("invert"),
    )
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_maintenance",
        vol.Required("entry_id"): str,
        vol.Required("enable"): bool,
    }
)
@websocket_api.async_response
async def ws_set_maintenance(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_set_maintenance(msg["enable"])
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_tank",
        vol.Required("entry_id"): str,
        vol.Required("tank"): vol.All(str, vol.Length(max=64)),
    }
)
@websocket_api.async_response
async def ws_set_tank(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_set_tank(msg["tank"])
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {vol.Required("type"): "chihiros_plus/complete_onboarding", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_complete_onboarding(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_complete_onboarding()
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/start_treatment",
        vol.Required("entry_id"): str,
        vol.Required("program"): str,
        vol.Optional("days", default=3): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=60)),
    }
)
@websocket_api.async_response
async def ws_start_treatment(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    try:
        await coordinator.async_start_temporary_program(msg["program"], msg["days"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_program", str(err))
        return
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {vol.Required("type"): "chihiros_plus/stop_treatment", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_stop_treatment(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_stop_treatment()
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command({vol.Required("type"): "chihiros_plus/list_switches"})
@callback
def ws_list_switches(hass, connection, msg: dict[str, Any]) -> None:
    """Switchable entities the user can pick as their CO₂ switch."""
    items = [
        {"entity_id": s.entity_id, "name": s.attributes.get("friendly_name", s.entity_id)}
        for s in hass.states.async_all(["switch", "input_boolean"])
    ]
    items.sort(key=lambda x: x["name"].lower())
    connection.send_result(msg["id"], {"switches": items})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_co2",
        vol.Required("entry_id"): str,
        vol.Required("switch"): vol.Any(None, str),
        vol.Optional("before_on", default=60): vol.All(int, vol.Range(min=0, max=360)),
        vol.Optional("before_off", default=60): vol.All(int, vol.Range(min=0, max=360)),
    }
)
@websocket_api.async_response
async def ws_set_co2(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_set_co2(msg["switch"], msg["before_on"], msg["before_off"])
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "chihiros_plus/set_rgbw",
        vol.Required("entry_id"): str,
        vol.Required("r"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Required("g"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Required("b"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Required("w"): vol.All(int, vol.Range(min=0, max=100)),
    }
)
@websocket_api.async_response
async def ws_set_rgbw(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    await coordinator.async_set_manual_rgbw(RGBW(msg["r"], msg["g"], msg["b"], msg["w"]))
    connection.send_result(msg["id"], coordinator.snapshot())


@websocket_api.websocket_command(
    {vol.Required("type"): "chihiros_plus/emergency_off", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_emergency_off(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    ok = await coordinator.async_emergency_off()
    connection.send_result(msg["id"], {"confirmed": ok, **coordinator.snapshot()})


@websocket_api.websocket_command(
    {vol.Required("type"): "chihiros_plus/identify", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_identify(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    ok = await coordinator.async_identify()
    connection.send_result(msg["id"], {"identified": ok, **coordinator.snapshot()})


@websocket_api.websocket_command(
    {vol.Required("type"): "chihiros_plus/reconnect", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_reconnect(hass, connection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unknown device")
        return
    ok = await coordinator.async_reconnect()
    connection.send_result(msg["id"], {"reconnected": ok, **coordinator.snapshot()})
