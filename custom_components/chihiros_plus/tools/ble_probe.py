"""Read-only BLE probe for a Chihiros lamp.

Scans for likely Chihiros devices, connects to the first match, and lists its
GATT services/characteristics. Confirms the Nordic-UART service + RX/TX chars
we rely on. Does NOT write anything to the lamp.

Usage: python probe.py [scan_seconds]
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

UART_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
PREFIXES = ("DYSIL", "DY")  # DYSIL = WRGB II Slim; DY = broader Chihiros family


async def main(scan_seconds: float) -> None:
    print(f"Scanning {scan_seconds:.0f}s for BLE devices...\n")
    found = await BleakScanner.discover(timeout=scan_seconds, return_adv=True)

    chihiros = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        has_uart = UART_SERVICE.lower() in [s.lower() for s in (adv.service_uuids or [])]
        is_chihiros = name.upper().startswith(PREFIXES) or has_uart
        tag = "  <-- CHIHIROS?" if is_chihiros else ""
        if is_chihiros:
            chihiros.append((dev, adv, name))
        print(f"  {dev.address}  rssi={adv.rssi:>4}  name={name!r}"
              f"  uart={'yes' if has_uart else 'no'}{tag}")

    if not chihiros:
        print("\nNo Chihiros-looking device found.")
        print("Checklist: My Chihiros app fully closed? Lamp powered + in range?")
        print("Terminal has macOS Bluetooth permission? (System Settings > Privacy)")
        return

    dev, adv, name = chihiros[0]
    print(f"\nConnecting to {name!r} ({dev.address})...")
    async with BleakClient(dev) as client:
        print(f"Connected: {client.is_connected}\n")
        svc_ok = rx_ok = tx_ok = False
        for service in client.services:
            print(f"[service] {service.uuid}")
            if service.uuid.lower() == UART_SERVICE:
                svc_ok = True
            for ch in service.characteristics:
                props = ",".join(ch.properties)
                mark = ""
                if ch.uuid.lower() == UART_RX:
                    rx_ok = True
                    mark = "  <-- RX (write target)"
                if ch.uuid.lower() == UART_TX:
                    tx_ok = True
                    mark = "  <-- TX (notify source)"
                print(f"    [char] {ch.uuid}  props=({props}){mark}")

        print("\n--- verdict ---")
        print(f"Advertised name : {name!r}  (prefix match: {name.upper().startswith(PREFIXES)})")
        print(f"Nordic UART svc : {'FOUND' if svc_ok else 'MISSING'}")
        print(f"RX write char   : {'FOUND' if rx_ok else 'MISSING'}")
        print(f"TX notify char  : {'FOUND' if tx_ok else 'MISSING'}")
        # Does the write char support write-with-response? Key for 'confirmed'.
        for service in client.services:
            for ch in service.characteristics:
                if ch.uuid.lower() == UART_RX:
                    wwr = "write" in ch.properties
                    wnr = "write-without-response" in ch.properties
                    print(f"RX supports     : write-with-response={wwr}, "
                          f"write-without-response={wnr}")


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    asyncio.run(main(secs))
