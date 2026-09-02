<p align="center">
  <img src="custom_components/aqua_chihiros/brand/logo.svg" width="180" alt="AquaChihiros">
</p>

<h1 align="center">AquaChihiros</h1>

<p align="center">
  A standalone Home Assistant integration for Chihiros BLE aquarium lights —
  local control, an aquarium-grade lighting engine, and a Bluetooth watchdog.
</p>

<p align="center">
  <a href="https://github.com/joohann/aqua_chihiros/actions/workflows/hassfest.yml"><img src="https://github.com/joohann/aqua_chihiros/actions/workflows/hassfest.yml/badge.svg" alt="hassfest"></a>
  <a href="https://github.com/joohann/aqua_chihiros/actions/workflows/validate.yml"><img src="https://github.com/joohann/aqua_chihiros/actions/workflows/validate.yml/badge.svg" alt="HACS"></a>
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=joohann&repository=aqua_chihiros&category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open in HACS">
  </a>
</p>

<p align="center"><sub>Click the badge to add this repository to HACS in your Home Assistant.</sub></p>

---

## What it does

This integration controls Chihiros aquarium lights **entirely locally over
Bluetooth Low Energy (BLE)** — no cloud account, no dependency on the *My
Chihiros* app. It is designed as a complete **aquarium lighting controller**,
not just a "Bluetooth remote for a lamp":

- ☀️ **Aquarium Light Engine** — one generic engine simulates a full day
  (dawn → sunrise → peak → sunset → dusk → moonlight → night) from a small set
  of parameters, with smooth interpolation between phases.
- 🐟 **Programs / presets** — Natural Day, Plant Growth, Low Tech, High Tech,
  Moonlight, Algae Protection (early stage), Plant Recovery. Each preset is
  *only parameters*; they all share the same engine.
- 🌇 **Follow the sun** — anchors the day to your real local sunrise/sunset,
  with a configurable photoperiod (shorten the day from the front — useful
  against algae). Manual start/length is always possible.
- 🛡️ **Bluetooth Watchdog** — a core safety component. Retries and reconnects
  on failure, tracks connection state, and **never reports a command as
  confirmed unless the lamp acknowledged it** (desired vs confirmed).
- 🧽 **Maintenance mode** — interrupt the program with full white light for
  cleaning, then resume.
- ▶️ **Preview on lamp** — play a whole day on the lamp in ~30 s to see the
  program in action.
- 🐟🐟 **Tanks / groups** — control multiple lamps over one aquarium together.
- 🖥️ **Custom sidebar panel** — live light curve, program picker, schedule,
  and per-lamp watchdog status.

> There is **no official Chihiros API or SDK**. "The protocol" here is the
> local, reverse-engineered BLE protocol (see *Acknowledgements*). Anything not
> proven against hardware is deliberately not implemented.

## Supported models

| Model | Status |
|---|---|
| Chihiros **WRGB II Slim** | ✅ Verified on real hardware |
| Chihiros **WRGB II Pro** | ✅ Verified on real hardware |

The architecture is model-generic (device abstraction + capability registry),
so more Chihiros models can be added once their behaviour is verified. If you
have another model and want to help verify it, open an issue.

## Requirements

- Home Assistant **2024.12** or newer.
- Bluetooth in Home Assistant — a supported local adapter **or** an
  [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html).
- The lamp must be **within good BLE range** of a *connectable* adapter/proxy
  (see [Bluetooth range](#bluetooth-range) — this is the #1 cause of problems).

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/joohann/aqua_chihiros` as category **Integration**.
3. Install **Chihiros Aquarium Light**, then restart Home Assistant.

### Manual

Copy `custom_components/aqua_chihiros/` into your Home Assistant
`config/custom_components/` directory and restart.

## Adding a lamp

1. Close the **My Chihiros** app (a BLE lamp accepts only one connection at a
   time).
2. Home Assistant usually **auto-discovers** the lamp — you'll see a *Chihiros
   discovered* card in **Settings → Devices & Services**.
3. Otherwise: **+ Add Integration → Chihiros**, and pick the lamp.

Each lamp becomes its own device with a `light`, sensors, numbers, a program
`select`, and buttons.

## Bluetooth range

BLE lamps need a *connectable* adapter close by. Advertisements (discovery) can
be picked up from far away, but **connecting** needs a good signal
(better than roughly **−80 dBm**). If the connection sensor stays on
*Reconnecting* and the logs show `ESP_GATT_ERROR`, the adapter/proxy is too far.

- Best fix: place a small **ESP32 Bluetooth Proxy** right next to the tank.
- Old CSR8510 (CSR chip) USB dongles are unreliable for connections — prefer a
  Realtek RTL8761B dongle (e.g. TP-Link UB500) or an ESP32 proxy.

## The panel

A **Aquarium** entry appears in the sidebar (dragon icon). It shows:

- the live 24-hour light curve with a "now" marker;
- the current brightness and per-channel R/G/B/W output;
- **desired vs confirmed** status (honest — "Applying…", "confirmed", or
  "not confirmed");
- the program picker (grouped *with moonlight* / *dark night*);
- the schedule (follow-sun, start time, day length) in a collapsible section;
- **Preview on lamp**, **Maintenance**, **Reconnect**, **Turn off**;
- tank grouping (give lamps the same tank name to control them together).

## Programs

Programs define parameters only; the engine renders them. Presets are
conservative starting points, **not guarantees** — e.g. "Plant Growth" does not
promise better growth, and "Algae Protection" is a supporting measure, not a
cure.

| Program | Idea |
|---|---|
| Natural Day | Balanced day with a soft moonlight |
| Plant Growth | Tighter photoperiod, higher intensity, dark night |
| Low Tech | Gentle, low intensity, long ramps |
| High Tech | Strong intensity (configurable), dark night |
| Moonlight | Bounded night-only moonlight |
| Algae Protection (early) | Short photoperiod, lower intensity, optional midday pause |
| Plant Recovery | Stable, moderate, consistent photoperiod |

## Services

- `aqua_chihiros.apply_preset` — switch to a built-in program
- `aqua_chihiros.set_rgbw` — set all four channels directly (manual mode)
- `aqua_chihiros.start_algae_protection` — run algae protection for N days, then revert
- `aqua_chihiros.sync_time` — push HA local time to the lamp's clock
- `aqua_chihiros.emergency_off` — attempt immediate off and report if confirmed

## Fail-safe behaviour & limitations

- The integration **never assumes a command succeeded** without a
  write-with-response acknowledgement. When the link is down, the desired state
  is shown but the confirmed state is **UNKNOWN**.
- A BLE device **cannot be turned off if no BLE link is possible at all** — the
  panel/emergency-off will report that it could not be confirmed.
- The watchdog surfaces prolonged outages as notifications (warning/critical).
- Uploading the schedule to the lamp's **on-device auto mode** (so it keeps a
  correct day/night cycle even during a total BLE loss) is a planned hardware
  fail-safe; it is intentionally not shipped until its exact frame format is
  verified against hardware.

## Troubleshooting

- **Stuck on *Reconnecting* / `ESP_GATT_ERROR`** → weak signal; move a proxy
  closer (see [Bluetooth range](#bluetooth-range)).
- **Not discovered** → the My Chihiros app is still connected, or the lamp is
  out of range of a connectable adapter.
- **"Applying to lamp…" never confirms** → the lamp isn't acknowledging; check
  the connection sensor and range.

### Debug logging

```yaml
# Developer Tools → Actions → logger.set_level
custom_components.aqua_chihiros: debug
bleak_retry_connector: debug
habluetooth: debug
```

## Acknowledgements

The local BLE protocol used here was informed by public reverse-engineering
work, in particular
[TheMicDiet/chihiros-led-control](https://github.com/TheMicDiet/chihiros-led-control)
and its protocol documentation. This project is an independent implementation
with its own architecture; it is not a fork.

## License

[MIT](LICENSE) © Johann Huwaë
