# Changelog

## v0.8.5 — Notice a lost lamp, and keep Moonlight on

### Summary

If the lamp dropped off Bluetooth while its output wasn't changing (for
example all night on Moonlight), the integration never noticed: no
notification, the connection still showed "connected", and a lamp that had
power-cycled stayed dark even though Moonlight was enabled.

### The problem

To avoid needless Bluetooth traffic, an unchanged output that the lamp had
already confirmed is not sent again. During a long steady phase nothing was
written at all, so a lost link was only discovered at the next colour change,
and the lamp was never told again what it should be showing.

Separately, the "unreachable" notifications were timed from the last
successful write. After a long quiet period that could jump straight to
"critical" with a misleading duration, and a lamp that was never reached since
Home Assistant started produced no notification at all.

### The fix

- **Health check twice an hour:** every 30 minutes the current output is sent
  again, even if it hasn't changed. This detects a lost link and re-applies the
  desired light (e.g. Moonlight after the lamp reset).
- **Notifications timed from the start of the outage:** the 2 / 10 / 30 minute
  warnings now count from the first failed attempt, and also fire when the lamp
  was never reached since startup.
- **Events for automations:** `chihiros_plus_unreachable` (with `name`,
  `level`, `minutes`) and `chihiros_plus_reconnected` are fired, so you can send
  a phone notification from an automation. The persistent notification is
  dismissed automatically once the lamp is reachable again.

## v0.8.4 — Moonlight no longer stays on all night after a reboot

### Summary

Fixes a bug where the lamp would come back on — and Moonlight would burn all
night — after a Home Assistant restart, even though it had been turned off (or
set to a manual colour) beforehand. The off / manual state is now saved and
restored across restarts, so a reboot no longer silently resumes the program.

### The problem

When you turned the lamp **off** in Home Assistant, or set a **manual colour**,
the integration only changed an in-memory setting on the coordinator
(`self._mode` → `off` / `manual`). That choice was **never written to the
config entry**, so it existed only until the next restart.

On startup the coordinator always initialised the mode back to
`program`. That meant that after any Home Assistant reboot the integration
forgot the lamp had been turned off and immediately resumed the active program.
If that program had Moonlight-at-night enabled in **"all night"** mode, the
Moonlight would then keep glowing until the next lights-on time — every single
night a restart happened.

Because Home Assistant restarts (updates, add-on installs, host reboots, config
reloads) are common, a lamp that was meant to be off could end up **on more
than it was off** over the course of a week.

The light engine itself was correct: Moonlight filling the night is intended
behaviour for the "all night" setting. The defect was purely that the
**off / manual state did not survive a restart**.

### The fix

- The current mode (and the manual colour when in manual/off) is now
  **persisted to the config entry options** whenever it changes, via a new
  `_persist_mode()` helper called from `async_set_manual_rgbw()` and
  `async_emergency_off()`.
- On startup the coordinator **restores that saved mode**, so turning the lamp
  off now survives a reboot instead of falling back to the program. A running
  timed treatment (Blackout / Algae Protection) still takes priority and forces
  program mode, as before.
- Selecting a program (or changing schedule, follow-sun, or Moonlight settings)
  now records `mode = program`, so a previously saved "off" state is cleared and
  cannot reappear on a later restart.

No configuration changes are required. After updating, turning the lamp off will
remain off across Home Assistant restarts.
