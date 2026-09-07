"""Chihiros custom sidebar panel registration.

Adds a single sidebar entry ("Aquarium") that renders the web component in
frontend/chihiros-panel.js in the main content area — the same approach used
by the Nida and NL-Alert panels. It does NOT add a second sidebar; it is one
icon in Home Assistant's existing sidebar.

Registered once for the integration (guarded), regardless of how many lamps
are configured. Static files are served with a ?v=<version> cache-buster so a
kiosk tablet re-fetches the bundle after an update.
"""
from __future__ import annotations

import logging
import os

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "chihiros_plus"
PANEL_TITLE = "Chihiros Plus"
PANEL_ICON = "chihiros_plus:dragon"  # custom brand dragon (frontend/chihiros-icons.js)
STATIC_URL = "/chihiros_plus_panel_files"
FRONTEND_SCRIPT_URL = f"{STATIC_URL}/chihiros-panel.js"
ICONS_SCRIPT_URL = f"{STATIC_URL}/chihiros-icons.js"
_STATIC_KEY = f"{DOMAIN}_panel_static_registered"
_PANEL_KEY = f"{DOMAIN}_panel_registered"
_ICONS_KEY = f"{DOMAIN}_icons_registered"


async def _asset_version(hass: HomeAssistant) -> str:
    integration = await async_get_integration(hass, DOMAIN)
    return integration.version or "0"


async def async_register_static(hass: HomeAssistant) -> None:
    if hass.data.get(_STATIC_KEY):
        return
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, frontend_dir, cache_headers=False)]
    )
    hass.data[_STATIC_KEY] = True


async def async_register_icons(hass: HomeAssistant) -> None:
    """Load the custom icon set so 'chihiros_plus:dragon' is usable as an icon.

    Uses frontend.add_extra_js_url (the pattern HACS uses for its own sidebar
    icon). Registered once and independent of the panel, so the icon works even
    if the sidebar panel is disabled.
    """
    if hass.data.get(_ICONS_KEY):
        return
    await async_register_static(hass)
    version = await _asset_version(hass)
    frontend.add_extra_js_url(hass, f"{ICONS_SCRIPT_URL}?v={version}")
    hass.data[_ICONS_KEY] = True


async def async_register_panel(hass: HomeAssistant) -> None:
    await async_register_icons(hass)
    if hass.data.get(_PANEL_KEY) or PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        return
    await async_register_static(hass)
    version = await _asset_version(hass)
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="chihiros-panel",
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{FRONTEND_SCRIPT_URL}?v={version}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        embed_iframe=False,
        require_admin=False,
    )
    hass.data[_PANEL_KEY] = True
    _LOGGER.debug("Chihiros panel registered at /%s (v%s)", PANEL_URL_PATH, version)


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    if PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
    hass.data.pop(_PANEL_KEY, None)
