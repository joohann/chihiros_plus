"""Constants for the Chihiros aquarium lighting integration.

This is a standalone Home Assistant integration for Chihiros BLE aquarium
lights (initial target: WRGB II Slim). It talks to the lamp entirely over
the local Nordic-UART BLE protocol — there is no official Chihiros cloud
API; "the protocol" here means the reverse-engineered local BLE protocol.

Nothing in this module imports Home Assistant, so it can be imported from
the pure protocol/engine layers as well.
"""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "aqua_chihiros"

# --- BLE transport (Nordic UART Service) ------------------------------------
# Proven values, from TheMicDiet/chihiros-led-control docs/protocol.md.
UART_SERVICE_UUID: Final = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX_CHAR_UUID: Final = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # HA -> lamp (write)
UART_TX_CHAR_UUID: Final = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # lamp -> HA (notify)

# BLE advertised-name prefixes used for discovery. Chihiros devices advertise
# a model-specific prefix followed by a serial. The most robust discovery
# signal is the Nordic UART service UUID (UART_SERVICE_UUID) being advertised;
# the name prefix is a secondary hint used to guess the model.
#   DYSL...   -> WRGB II Slim  (CONFIRMED on real hardware: "DYSL30D6469AAA95ED")
#   DYSIL...  -> WRGB II Slim  (reported variant, e.g. "DYSILNF5EOACC1EC37")
#   DYWPRO... -> WRGB II Pro   (CONFIRMED on real hardware: "DYWPRO60C7B9B48D9C20")
# All Chihiros units seen so far share the "DY" family prefix; extend the map
# as more models are verified.
KNOWN_NAME_PREFIXES: Final[dict[str, str]] = {
    "DYSL": "wrgb_ii_slim",
    "DYSIL": "wrgb_ii_slim",
    "DYWPRO": "wrgb_ii_pro",
}
# Broad family prefix — used together with the UART service to decide a device
# is "probably Chihiros" during discovery, even for an unmapped model.
FAMILY_NAME_PREFIX: Final = "DY"

# Channel index -> logical channel, for RGBW devices (WRGB II Slim).
CHANNEL_RED: Final = 0
CHANNEL_GREEN: Final = 1
CHANNEL_BLUE: Final = 2
CHANNEL_WHITE: Final = 3

# --- Watchdog / connection states -------------------------------------------
STATE_CONNECTED: Final = "connected"
STATE_DEGRADED: Final = "degraded"
STATE_RECONNECTING: Final = "reconnecting"
STATE_OFFLINE: Final = "offline"
STATE_ERROR: Final = "error"
STATE_UNKNOWN: Final = "unknown"

# Sentinel for "we have no confirmation of the lamp's actual state". The
# integration must never report a value as confirmed unless the lamp
# acknowledged it — an unconfirmed desired value stays UNKNOWN.
CONFIRMED_UNKNOWN: Final = None
