"""Config flow: discover a Chihiros lamp over Bluetooth and add it.

Discovery matches on the Nordic UART service (robust) and the DY* name family.
The model is guessed from the advertised name prefix; the user confirms.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from . import CONF_MODEL
from .const import DOMAIN, FAMILY_NAME_PREFIX, UART_SERVICE_UUID
from .devices import model_for_name


def _looks_like_chihiros(info: BluetoothServiceInfoBleak) -> bool:
    name = (info.name or "").upper()
    has_uart = UART_SERVICE_UUID.lower() in [u.lower() for u in info.service_uuids]
    return has_uart or name.startswith(FAMILY_NAME_PREFIX)


class ChihirosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chihiros aquarium lights."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None
        self._discovered_map: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a lamp discovered automatically over Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or "Chihiros"}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered is not None
        info = self._discovered
        if user_input is not None:
            return self._create_entry(info)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": info.name or info.address},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual add: pick from currently-discovered, unconfigured lamps."""
        if user_input is not None:
            info = self._discovered_map[user_input[CONF_ADDRESS]]
            await self.async_set_unique_id(info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create_entry(info)

        current = self._async_current_ids()
        self._discovered_map = {
            info.address: info
            for info in async_discovered_service_info(self.hass)
            if _looks_like_chihiros(info) and info.address not in current
        }
        if not self._discovered_map:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{info.name or 'Chihiros'} ({addr})"
                            for addr, info in self._discovered_map.items()
                        }
                    )
                }
            ),
        )

    def _create_entry(self, info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        model = model_for_name(info.name or "")
        return self.async_create_entry(
            title=info.name or "Chihiros Light",
            data={
                CONF_ADDRESS: info.address,
                CONF_MODEL: model.key if model else "wrgb_ii_slim",
            },
            # New lamps start un-onboarded so the panel offers a first-time
            # setup. Existing entries have no such key -> treated as onboarded.
            options={"onboarded": False},
        )
