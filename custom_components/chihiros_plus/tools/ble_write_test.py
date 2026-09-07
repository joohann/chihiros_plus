"""Gentle end-to-end write test against a real Chihiros lamp.

Drives the lamp using THIS integration's own protocol layer, so a successful
run proves our checksum/frame/manual-mode encoding controls real hardware —
not just the in-memory fake device.

Safety: it only ever sets low brightness, and ALWAYS turns every channel back
to 0 in a finally block, even on error or Ctrl-C. Uses write-with-response so
each command is acknowledged by the lamp (our "confirmed" signal).

Run it yourself in Terminal.app (needs macOS Bluetooth permission):

    cd /Volumes/config/custom_components/chihiros_plus/tools
    ./.probe-venv/bin/pip install -q bleak   # if not already
    ./.probe-venv/bin/python ble_write_test.py

Close the My Chihiros app first (one BLE connection at a time).
"""
import asyncio
import sys
from pathlib import Path

# Make `chihiros_plus` importable (custom_components is parents[2] of this file).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bleak import BleakClient, BleakScanner  # noqa: E402

from chihiros_plus.const import (  # noqa: E402
    CHANNEL_WHITE,
    UART_RX_CHAR_UUID,
    UART_SERVICE_UUID,
    UART_TX_CHAR_UUID,
)
from chihiros_plus.protocol import (  # noqa: E402
    RGBW,
    MessageIdCounter,
    enter_manual_mode,
    parse_notification,
    set_channel_brightness,
    set_rgbw,
)

PREFIXES = ("DYSL", "DYSIL", "DY")


async def find_lamp(seconds: float):
    devices = await BleakScanner.discover(timeout=seconds, return_adv=True)
    for dev, adv in devices.values():
        name = (adv.local_name or dev.name or "").upper()
        has_uart = UART_SERVICE_UUID.lower() in [s.lower() for s in (adv.service_uuids or [])]
        if name.startswith(PREFIXES) or has_uart:
            return dev, (adv.local_name or dev.name or "")
    return None, None


async def main() -> None:
    dev, name = await find_lamp(12.0)
    if dev is None:
        print("No Chihiros lamp found. Is the My Chihiros app closed and the lamp in range?")
        return
    print(f"Found {name!r} ({dev.address}). Connecting...")

    mid = MessageIdCounter()

    def on_notify(_char, data: bytearray) -> None:
        resp = parse_notification(bytes(data))
        print(f"  <- notify {bytes(data).hex()}  parsed={resp}")

    async with BleakClient(dev) as client:
        print(f"Connected: {client.is_connected}")
        try:
            await client.start_notify(UART_TX_CHAR_UUID, on_notify)
        except Exception as err:  # notifications are a bonus, not required
            print(f"  (could not enable notifications: {err})")

        async def send(frame: bytes, label: str) -> None:
            # response=True -> write-with-response -> delivery acknowledged.
            await client.write_gatt_char(UART_RX_CHAR_UUID, frame, response=True)
            print(f"  -> {label}: {frame.hex()}  (acknowledged)")

        try:
            print("\nStep 1: manual mode")
            await send(enter_manual_mode(mid), "enter_manual")
            await asyncio.sleep(0.5)

            print("Step 2: white channel to a gentle 20%")
            await send(set_channel_brightness(CHANNEL_WHITE, 20, mid), "white=20")
            await asyncio.sleep(2.0)

            print("Step 3: soft RGBW test (15/15/25/10)")
            for frame in set_rgbw(RGBW(15, 15, 25, 10), mid):
                await send(frame, "rgbw")
            await asyncio.sleep(2.0)

            print("\nSUCCESS: real lamp responded to our own protocol frames.")
        finally:
            print("Restoring: all channels -> 0 (off)")
            for frame in set_rgbw(RGBW(0, 0, 0, 0), mid):
                try:
                    await client.write_gatt_char(UART_RX_CHAR_UUID, frame, response=True)
                except Exception as err:  # pragma: no cover
                    print(f"  ! failed to zero a channel: {err}")
            print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
