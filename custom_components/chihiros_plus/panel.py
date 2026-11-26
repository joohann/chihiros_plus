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

from homeassistant.components import frontend
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
DONATE_SCRIPT_URL = f"{STATIC_URL}/majikan-donate.js"
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
    # The reusable donate web component (<majikan-donate>) used in the panel.
    frontend.add_extra_js_url(hass, f"{DONATE_SCRIPT_URL}?v={version}")
    hass.data[_ICONS_KEY] = True


async def async_sync_panel(hass: HomeAssistant) -> None:
    """Register, update or remove the shared panel to match the options.

    Two independent choices, each "on" unless every lamp has it off:
      * ``sidebar``    -> an entry in Home Assistant's sidebar;
      * ``gear_panel`` -> the gear on the integration page opens this panel
                          (``config_panel_domain``) instead of the options
                          dialog. The panel then holds every setting.
    With both off the panel is removed and the gear opens the options dialog,
    which is also where both can be switched back on.

    Registered with ``update`` instead of remove-and-add: a panel that
    disappears makes the frontend jump to the default dashboard, which would
    happen on every toggle in the settings dialog.
    """
    from . import gear_wanted, sidebar_wanted

    await async_register_icons(hass)
    sidebar = sidebar_wanted(hass)
    gear = gear_wanted(hass)
    if not sidebar and not gear:
        async_remove_panel(hass)
        return
    await async_register_static(hass)
    version = await _asset_version(hass)
    state = (sidebar, gear, version)
    registered = PANEL_URL_PATH in hass.data.get("frontend_panels", {})
    if registered and hass.data.get(_PANEL_KEY) == state:
        return
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE if sidebar else None,
        sidebar_icon=PANEL_ICON if sidebar else None,
        frontend_url_path=PANEL_URL_PATH,
        require_admin=False,
        config_panel_domain=DOMAIN if gear else None,
        show_in_sidebar=sidebar,
        update=registered,
        config={
            "_panel_custom": {
                "name": "chihiros-panel",
                "module_url": f"{FRONTEND_SCRIPT_URL}?v={version}",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
    )
    hass.data[_PANEL_KEY] = state
    _LOGGER.debug(
        "Chihiros panel at /%s (v%s, sidebar=%s, gear=%s)",
        PANEL_URL_PATH, version, sidebar, gear,
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    if PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
    hass.data.pop(_PANEL_KEY, None)
