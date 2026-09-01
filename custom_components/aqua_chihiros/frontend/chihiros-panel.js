/**
 * Chihiros aquarium light panel.
 *
 * A single sidebar view that shows the live light curve, current output,
 * program choice and per-lamp watchdog status for every configured Chihiros
 * lamp. It talks to the backend only through the aqua_chihiros/* websocket
 * commands (see websocket.py) — it computes nothing itself.
 *
 * Design follows the approved mockup: calm single column, aqua accent, blended
 * with the active Home Assistant theme. No second sidebar — this renders in the
 * main content area of HA's existing sidebar entry.
 */
const PROGRAMS = [
  ["natural_day", "Natural Day"],
  ["plant_growth", "Plant Growth"],
  ["low_tech", "Low Tech"],
  ["high_tech", "High Tech"],
  ["moonlight", "Moonlight"],
  ["algae_protection_early", "Algae Protection"],
  ["plant_recovery", "Plant Recovery"],
];
// Programs grouped by whether they include a night moonlight phase.
const WITH_MOON = [
  ["natural_day", "Natural Day"],
  ["low_tech", "Low Tech"],
  ["plant_recovery", "Plant Recovery"],
  ["moonlight", "Moonlight"],
];
const WITHOUT_MOON = [
  ["plant_growth", "Plant Growth"],
  ["high_tech", "High Tech"],
  ["algae_protection_early", "Algae Protection"],
];
const CH = [["R", "#e23d55"], ["G", "#2fae54"], ["B", "#3f7fe0"], ["W", "#b79a3f"]];
const CONN_LABEL = {
  connected: "Connected", degraded: "Degraded", reconnecting: "Reconnecting",
  offline: "Offline", error: "Error", unknown: "Unknown",
};
const CONN_COLOR = {
  connected: "var(--success-color,#0f9d7a)", degraded: "var(--warning-color,#d9971f)",
  reconnecting: "var(--warning-color,#d9971f)", offline: "var(--error-color,#d8434f)",
  error: "var(--error-color,#d8434f)", unknown: "var(--disabled-text-color,#8a8a8a)",
};

class ChihirosPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._devices = [];
    this._curve = null;
    this._selected = null;
    this._timer = null;
    this._built = false;
    this._loading = false;
    this._busy = false;            // an action (program/reconnect/off) in flight
    this._confirming = false;      // waiting for the lamp to acknowledge a change
    this._lastInteraction = 0;
    this._previewRAF = null;
    this._playRAF = null;
    this._playing = false;
    this._narrow = false;          // HA sets this true on mobile/narrow layouts
    this._collapsed = { schedule: true, tanks: true };   // compact by default
  }

  set narrow(value) {
    this._narrow = !!value;
    if (this._built) this._syncTopbar();
  }

  _sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  // Poll a few times until the lamp confirms the change (or we give up).
  async _awaitConfirm() {
    this._confirming = true;
    this._render();
    for (let i = 0; i < 8; i++) {
      await this._sleep(1200);
      await this._load();
      const members = this._members();
      if (members.length && members.every((d) => d.is_confirmed)) break;
      if (members.some((d) => d.connection !== "connected" && d.connection !== "reconnecting")) break;
    }
    this._confirming = false;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      this._built = true;
      this._load();
    }
  }

  connectedCallback() {
    this._timer = setInterval(() => {
      // Don't refresh mid-action or right after the user touched something —
      // it would wipe the optimistic highlight before the server confirms.
      if (this._busy || Date.now() - this._lastInteraction < 4000) return;
      this._load();
    }, 15000);
  }
  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }

  async _ws(msg) {
    return this._hass.connection.sendMessagePromise(msg);
  }

  _toast(message, kind = "info") {
    const el = this.shadowRoot.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.className = `toast show ${kind}`;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.className = "toast"; }, 3000);
  }

  async _load() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    try {
      const res = await this._ws({ type: "aqua_chihiros/list_devices" });
      this._devices = res.devices || [];
      // Group lamps by tank; lamps sharing a tank name are controlled together.
      this._tanks = {};
      for (const d of this._devices) {
        const t = d.tank || d.name;
        (this._tanks[t] = this._tanks[t] || []).push(d);
      }
      const names = Object.keys(this._tanks);
      if (!this._selected || !this._tanks[this._selected]) this._selected = names[0] || null;
      const leader = this._leader();
      if (leader) {
        this._curve = await this._ws({ type: "aqua_chihiros/get_curve", entry_id: leader.entry_id });
      }
      this._render();
    } catch (err) {
      this._renderError(err);
    } finally {
      this._loading = false;
    }
  }

  // A tank's "leader" (first lamp) represents its shared program/schedule; all
  // members are kept in sync by fanning actions out to every member.
  _members() { return (this._tanks && this._tanks[this._selected]) || []; }
  _memberIds() { return this._members().map((d) => d.entry_id); }
  _leader() { return this._members()[0] || null; }
  _dev() { return this._leader(); }              // alias used across render code

  async _fanout(build) {
    await Promise.allSettled(this._memberIds().map((id) => this._ws(build(id))));
  }

  // -- actions --------------------------------------------------------------
  async _setProgram(program) {
    this._lastInteraction = Date.now();
    const label = (PROGRAMS.find((p) => p[0] === program) || [null, program])[1];
    // Optimistic: highlight every lamp in the tank + "applying" immediately.
    this._members().forEach((d) => { d.program_key = program; d.program_name = label; });
    this._confirming = true;
    this._render();
    this._toast(`Program → ${label}`);
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/set_program", entry_id: id, program }));
      await this._awaitConfirm();  // shows "Applying…" until the lamps acknowledge
    } catch (err) {
      this._confirming = false;
      this._toast("Failed to change program", "error");
      await this._load();
    }
  }

  async _emergencyOff() {
    this._lastInteraction = Date.now();
    this._busy = true;
    this._toast("Turning off…");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/emergency_off", entry_id: id }));
      this._toast("Turned off", "ok");
    } catch (err) {
      this._toast("Turn off failed", "error");
    } finally {
      this._busy = false;
      await this._load();
    }
  }

  async _reconnect() {
    this._lastInteraction = Date.now();
    this._busy = true;
    this._toast("Reconnecting…");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/reconnect", entry_id: id }));
      this._toast("Reconnect requested", "ok");
    } catch (err) {
      this._toast("Reconnect failed", "error");
    } finally {
      this._busy = false;
      await this._load();
    }
  }

  async _setTank(entryId, tank) {
    this._lastInteraction = Date.now();
    try {
      await this._ws({ type: "aqua_chihiros/set_tank", entry_id: entryId, tank });
      this._selected = tank || this._selected;   // follow the lamp into its tank
      this._toast("Tank updated ✓", "ok");
    } catch (err) {
      this._toast("Could not update tank", "error");
    }
    await this._load();
  }

  // -- rendering ------------------------------------------------------------
  _build() {
    this.shadowRoot.innerHTML =
      `<style>${STYLES}</style><div id="topbar"></div><div id="root"></div><div id="toast" class="toast"></div>`;
    this._syncTopbar();
  }

  // On mobile (HA sets `narrow`), a custom panel has no HA header, so there's
  // no way back to the sidebar. Render our own top bar with a menu button that
  // opens the HA sidebar via the standard hass-toggle-menu event.
  _syncTopbar() {
    const bar = this.shadowRoot.getElementById("topbar");
    if (!bar) return;
    if (!this._narrow) { bar.innerHTML = ""; return; }
    bar.innerHTML =
      `<button id="menu" class="menubtn" aria-label="Open Home Assistant menu">
         <svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2Z"/></svg>
       </button>
       <span class="tbtitle">AquaChihiros</span>`;
    const m = this.shadowRoot.getElementById("menu");
    if (m) m.addEventListener("click", () =>
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })));
  }

  _renderError(err) {
    this._syncTopbar();
    this.shadowRoot.getElementById("root").innerHTML =
      `<div class="card"><p class="muted">Could not reach the Chihiros integration.</p>
       <p class="mono">${(err && err.message) || err}</p></div>`;
  }

  _render() {
    this._syncTopbar();
    const root = this.shadowRoot.getElementById("root");
    if (!this._devices.length) {
      root.innerHTML = `<div class="pagehead"><div class="eyebrow">Aquarium light</div>
        <h1>Chihiros</h1></div>
        <div class="card"><p class="muted">No Chihiros lamps configured yet. Add one via
        Settings → Devices &amp; Services.</p></div>`;
      return;
    }
    const dev = this._dev();
    // Defensive defaults so a lagging/old snapshot never renders NaN.
    if (!Number.isFinite(dev.start_minute)) dev.start_minute = 420;        // 07:00
    if (!Number.isFinite(dev.day_length_minutes)) dev.day_length_minutes = 600; // 10 h
    if (!Array.isArray(dev.desired)) dev.desired = [0, 0, 0, 0];
    if (!Number.isFinite(dev.brightness)) dev.brightness = 0;
    const off = dev.brightness === 0;
    root.innerHTML = `
      <div class="pagehead">
        <div>
          <div class="eyebrow">Aquarium${this._members().length > 1 ? ` · ${this._members().length} lamps` : ""}</div>
          <h1>${esc(this._selected)}</h1>
        </div>
        ${Object.keys(this._tanks).length > 1 ? this._switcher() : ""}
      </div>

      <div class="statusline">
        <span class="led" style="background:${CONN_COLOR[dev.connection]}"></span>
        <span><b>${esc(dev.program_name)}</b> · ${esc(dev.phase)}</span>
        <span class="dot">•</span><span>${CONN_LABEL[dev.connection] || dev.connection}</span>
        ${dev.rssi != null ? `<span class="dot">•</span><span class="mono">${dev.rssi} dBm</span>` : ""}
      </div>

      <section class="card">
        <div class="curvehead">
          <span class="ct" id="pv-title">Today · ${esc(dev.program_name)}</span>
          <button class="preview" id="preview">▶ Preview on lamp</button>
        </div>
        <canvas id="curve" width="1160" height="260"></canvas>
        <div class="bright"><span class="big" id="pv-b">${dev.brightness}</span><span class="u">% brightness</span></div>
        <div class="chrow">
          ${CH.map(([lbl, col], i) => `<div class="ch"><div class="n" id="pv-ch-${i}" style="color:${col}">${dev.desired[i]}</div><div class="c">${lbl}</div></div>`).join("")}
        </div>
        ${dev.is_confirmed
          ? `<div class="confirm ok">✓ confirmed by lamp</div>`
          : this._confirming
            ? `<div class="confirm pending"><span class="spin"></span>Applying to lamp…</div>`
            : `<div class="confirm unk">? not confirmed — desired only</div>`}
      </section>

      <section class="card">
        <div class="lbl">Program</div>
        <div class="grouplbl">🌙 With moonlight</div>
        <div class="progs">
          ${WITH_MOON.map(([k, n]) => `<button class="prog ${k === dev.program_key ? "on" : ""}" data-prog="${k}">${n}</button>`).join("")}
        </div>
        <div class="grouplbl">🌑 Dark night</div>
        <div class="progs">
          ${WITHOUT_MOON.map(([k, n]) => `<button class="prog ${k === dev.program_key ? "on" : ""}" data-prog="${k}">${n}</button>`).join("")}
        </div>
        <div class="collhead" data-collapse="schedule">
          <span>Schedule &amp; timing</span>
          <span class="chev">${this._collapsed.schedule ? "▸" : "▾"}</span>
        </div>
        <div class="sched" ${this._collapsed.schedule ? "hidden" : ""}>
          <label class="sunrow">
            <input type="checkbox" id="follow-sun" ${dev.follow_sun ? "checked" : ""}>
            <span>🌇 Follow real sunset</span>
          </label>
          <div class="fields">
            <label class="field ${dev.follow_sun ? "dim" : ""}">
              <span>Start time ${dev.follow_sun ? "· auto" : ""}</span>
              <input type="time" id="sched-start" value="${minToTime(dev.start_minute)}" ${dev.follow_sun ? "disabled" : ""}>
            </label>
            <label class="field">
              <span>Day length <b id="sched-len-val">${(dev.day_length_minutes / 60).toFixed(1)} h</b></span>
              <input type="range" id="sched-len" min="1" max="24" step="0.5"
                     value="${(dev.day_length_minutes / 60).toFixed(1)}">
            </label>
          </div>
          ${dev.follow_sun
            ? `<div class="sunnote">Sunset anchored to the sun (${minToTime(dev.start_minute + dev.day_length_minutes)}). Lights start ${minToTime(dev.start_minute)} — change the length to shift the start.</div>`
            : `<div class="sunnote">Manual: ${minToTime(dev.start_minute)}–${minToTime(dev.start_minute + dev.day_length_minutes)}.</div>`}
        </div>
      </section>

      <section class="card">
        <div class="lbl">Lamps in this tank</div>
        ${this._members().map((d) => this._lampRow(d)).join("")}
        <button class="btn maint ${dev.maintenance ? "on" : ""}" id="maint">
          ${dev.maintenance ? "▶ Resume program" : "🧽 Maintenance — white 100%"}
        </button>
        <div class="btns">
          <button class="btn" id="reconnect">⟳ Reconnect</button>
          <button class="btn danger" id="off">⏻ Turn off</button>
        </div>
        <div class="collhead" data-collapse="tanks">
          <span>Group lamps into tanks</span>
          <span class="chev">${this._collapsed.tanks ? "▸" : "▾"}</span>
        </div>
        <div class="tankedit" ${this._collapsed.tanks ? "hidden" : ""}>
          <p class="muted" style="margin:0 0 10px;font-size:12px">Give lamps the same tank name to control them together.</p>
          ${this._devices.map((d) => `
            <label class="tankrow">
              <span class="tankname">${esc(d.name)}</span>
              <input type="text" class="tankinput" data-tank="${d.entry_id}" value="${esc(d.tank)}" placeholder="Tank name">
            </label>`).join("")}
        </div>
      </section>

      <div class="foot mono">Local Bluetooth · no cloud · schedule stored on lamp</div>`;

    this.shadowRoot.querySelectorAll("[data-prog]").forEach((b) =>
      b.addEventListener("click", () => this._setProgram(b.dataset.prog)));
    this.shadowRoot.querySelectorAll("[data-sel]").forEach((b) =>
      b.addEventListener("click", () => { this._selected = b.dataset.sel; this._load(); }));
    const offBtn = this.shadowRoot.getElementById("off");
    if (offBtn) offBtn.addEventListener("click", () => this._emergencyOff());
    const rc = this.shadowRoot.getElementById("reconnect");
    if (rc) rc.addEventListener("click", () => this._reconnect());

    this.shadowRoot.querySelectorAll("[data-tank]").forEach((inp) =>
      inp.addEventListener("change", () => this._setTank(inp.dataset.tank, inp.value.trim())));

    const maint = this.shadowRoot.getElementById("maint");
    if (maint) maint.addEventListener("click", () => this._setMaintenance(!this._dev().maintenance));

    this.shadowRoot.querySelectorAll("[data-collapse]").forEach((h) =>
      h.addEventListener("click", () => {
        const key = h.dataset.collapse;
        this._collapsed[key] = !this._collapsed[key];
        this._render();
      }));

    const pv = this.shadowRoot.getElementById("preview");
    if (pv) pv.addEventListener("click", () => this._playOnLamp());

    const followSun = this.shadowRoot.getElementById("follow-sun");
    if (followSun) followSun.addEventListener("change", () => this._setFollowSun(followSun.checked));

    const start = this.shadowRoot.getElementById("sched-start");
    if (start) start.addEventListener("change", () =>
      this._setSchedule({ start_minute: timeToMin(start.value) }));

    const len = this.shadowRoot.getElementById("sched-len");
    const lenVal = this.shadowRoot.getElementById("sched-len-val");
    if (len) {
      len.addEventListener("input", () => { if (lenVal) lenVal.textContent = `${(+len.value).toFixed(1)} h`; });
      len.addEventListener("change", () =>
        this._setSchedule({ day_length_minutes: Math.round(+len.value * 60) }));
    }

    this._drawCurve();
  }

  async _setMaintenance(enable) {
    this._lastInteraction = Date.now();
    this._members().forEach((d) => { d.maintenance = enable; });   // optimistic
    this._confirming = true;
    this._render();
    this._toast(enable ? "Maintenance — white 100%" : "Resuming program…");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/set_maintenance", entry_id: id, enable }));
      await this._awaitConfirm();
    } catch (err) {
      this._confirming = false;
      this._toast("Could not switch", "error");
      await this._load();
    }
  }

  async _setFollowSun(enabled) {
    this._lastInteraction = Date.now();
    this._toast(enabled ? "Following the sun 🌇" : "Manual schedule");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/set_follow_sun", entry_id: id, enabled }));
      await this._awaitConfirm();
    } catch (err) {
      this._toast("Could not change", "error");
      await this._load();
    }
  }

  async _setSchedule(params) {
    this._lastInteraction = Date.now();
    this._toast("Updating schedule…");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/set_schedule", entry_id: id, ...params }));
      this._toast("Schedule updated ✓", "ok");
      await this._awaitConfirm();
    } catch (err) {
      this._toast("Could not update schedule", "error");
      await this._load();
    }
  }

  _updateReadout(minute, title) {
    const pts = this._curve.points;
    const val = (idx) => {
      for (let i = 0; i < pts.length - 1; i++) {
        if (minute >= pts[i].m && minute <= pts[i + 1].m) {
          const t = (minute - pts[i].m) / (pts[i + 1].m - pts[i].m || 1);
          return Math.round(pts[i].rgbw[idx] + (pts[i + 1].rgbw[idx] - pts[i].rgbw[idx]) * t);
        }
      }
      return pts[pts.length - 1].rgbw[idx];
    };
    const b = this.shadowRoot.getElementById("pv-b");
    if (b) b.textContent = Math.round(this._sampleAt(minute));
    for (let i = 0; i < 4; i++) {
      const el = this.shadowRoot.getElementById(`pv-ch-${i}`);
      if (el) el.textContent = val(i);
    }
    if (title) title.textContent = `Preview · ${minToTime(Math.round(minute))}`;
  }

  _rgbwAt(minute) {
    const pts = this._curve.points;
    const at = (idx) => {
      for (let i = 0; i < pts.length - 1; i++) {
        if (minute >= pts[i].m && minute <= pts[i + 1].m) {
          const t = (minute - pts[i].m) / (pts[i + 1].m - pts[i].m || 1);
          return Math.max(0, Math.min(100, Math.round(
            pts[i].rgbw[idx] + (pts[i + 1].rgbw[idx] - pts[i].rgbw[idx]) * t)));
        }
      }
      return pts[pts.length - 1].rgbw[idx];
    };
    return [at(0), at(1), at(2), at(3)];
  }

  // Fast-play the day AND drive the lamp along with it (throttled), then
  // resume the real program. Distinct from the visual-only Preview.
  _playOnLamp() {
    if (!this._curve) return;
    if (this._playRAF) { this._stopPlay(); return; }
    const dev = this._dev();
    this._playProgram = dev ? dev.program_key : "natural_day";
    this._playing = true;
    this._busy = true;                 // pause auto-refresh while playing
    const btn = this.shadowRoot.getElementById("preview");
    const title = this.shadowRoot.getElementById("pv-title");
    if (btn) btn.textContent = "■ Stop";
    this._toast("Playing on lamp…");
    const DURATION = 30000;            // slow enough that the lamp keeps up over BLE
    const startT = performance.now();
    let lastSend = 0;
    const step = (t) => {
      if (!this._playing) return;
      const frac = Math.min(1, (t - startT) / DURATION);
      const minute = frac * 1440;
      this._drawCurve(minute);
      this._updateReadout(minute, title);
      if (t - lastSend >= 1000) {       // throttle BLE writes to ~1/s
        lastSend = t;
        const [r, g, b, w] = this._rgbwAt(minute);
        this._fanout((id) => ({ type: "aqua_chihiros/set_rgbw", entry_id: id, r, g, b, w })).catch(() => {});
      }
      if (frac < 1) this._playRAF = requestAnimationFrame(step);
      else this._finishPlay();
    };
    this._playRAF = requestAnimationFrame(step);
  }

  async _finishPlay() {
    this._playing = false;
    if (this._playRAF) cancelAnimationFrame(this._playRAF);
    this._playRAF = null;
    const btn = this.shadowRoot.getElementById("preview");
    if (btn) btn.textContent = "▶ Preview on lamp";
    this._toast("Resuming program…");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/set_program", entry_id: id, program: this._playProgram }));
    } catch (err) { /* ignore */ }
    this._busy = false;
    await this._load();
  }

  _stopPlay() {
    this._finishPlay();
  }

  _switcher() {
    return `<div class="switch">${Object.keys(this._tanks).map((t) =>
      `<button data-sel="${esc(t)}" class="${t === this._selected ? "on" : ""}">${esc(t)}</button>`).join("")}</div>`;
  }

  _lampRow(d) {
    return `<div class="dev">
      <span class="led" style="background:${CONN_COLOR[d.connection]}"></span>
      <span class="nm">${esc(d.name)}</span>
      <span class="st" style="color:${CONN_COLOR[d.connection]}">${(CONN_LABEL[d.connection] || d.connection).toUpperCase()}</span>
      <span class="meta mono">${d.rssi != null ? d.rssi + " dBm" : "—"}</span></div>`;
  }

  _drawCurve(previewMinute) {
    const cv = this.shadowRoot.getElementById("curve");
    if (!cv || !this._curve) return;
    const ctx = cv.getContext("2d");
    const W = cv.width, H = cv.height, pL = 8, pR = 8, pT = 14, pB = 28;
    const pts = this._curve.points;
    const accent = getComputedStyle(this).getPropertyValue("--chihiros-accent") || "#0a9d94";
    const grid = getComputedStyle(this).getPropertyValue("--divider-color") || "#ddd";
    const muted = getComputedStyle(this).getPropertyValue("--secondary-text-color") || "#888";
    const surface = getComputedStyle(this).getPropertyValue("--card-background-color") || "#fff";
    const X = (m) => pL + (m / 1440) * (W - pL - pR);
    const Y = (b) => pT + (1 - b / 100) * (H - pT - pB);
    ctx.clearRect(0, 0, W, H);
    // hour ticks
    ctx.font = '16px monospace'; ctx.fillStyle = muted; ctx.textAlign = "center";
    for (let h = 0; h <= 24; h += 6) { ctx.globalAlpha = .7; ctx.fillText(String(h).padStart(2, "0"), X(h * 60), H - 8); ctx.globalAlpha = 1; }
    // area
    const g = ctx.createLinearGradient(0, pT, 0, H - pB);
    g.addColorStop(0, accent + "55"); g.addColorStop(1, accent + "08");
    ctx.beginPath(); ctx.moveTo(X(pts[0].m), H - pB);
    pts.forEach((p) => ctx.lineTo(X(p.m), Y(p.b)));
    ctx.lineTo(X(pts[pts.length - 1].m), H - pB); ctx.closePath();
    ctx.fillStyle = g; ctx.fill();
    // line
    ctx.beginPath(); ctx.strokeStyle = accent.trim() || "#0a9d94"; ctx.lineWidth = 3; ctx.lineJoin = "round";
    pts.forEach((p, i) => (i ? ctx.lineTo(X(p.m), Y(p.b)) : ctx.moveTo(X(p.m), Y(p.b))));
    ctx.stroke();
    // now marker (or the preview position while previewing)
    const nm = previewMinute != null ? previewMinute : this._curve.now_minute;
    const nb = this._sampleAt(nm);
    ctx.strokeStyle = "#e07d2f"; ctx.lineWidth = 2; ctx.setLineDash([4, 5]);
    ctx.beginPath(); ctx.moveTo(X(nm), pT); ctx.lineTo(X(nm), H - pB); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "#e07d2f"; ctx.beginPath(); ctx.arc(X(nm), Y(nb), 6, 0, 7); ctx.fill();
    ctx.fillStyle = surface.trim() || "#fff"; ctx.beginPath(); ctx.arc(X(nm), Y(nb), 2.5, 0, 7); ctx.fill();
  }

  _sampleAt(minute) {
    const pts = this._curve.points;
    for (let i = 0; i < pts.length - 1; i++) {
      if (minute >= pts[i].m && minute <= pts[i + 1].m) {
        const t = (minute - pts[i].m) / (pts[i + 1].m - pts[i].m || 1);
        return pts[i].b + (pts[i + 1].b - pts[i].b) * t;
      }
    }
    return pts[pts.length - 1].b;
  }
}

function minToTime(m) {
  m = ((Math.round(m) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
function timeToMin(v) {
  const [h, m] = (v || "0:0").split(":").map((n) => parseInt(n, 10) || 0);
  return h * 60 + m;
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const STYLES = `
  :host { --chihiros-accent:#0a9d94; display:block; }
  #topbar:not(:empty) { position:sticky; top:0; z-index:5; display:flex; align-items:center;
    gap:6px; height:52px; padding:0 6px;
    background:var(--app-header-background-color, var(--primary-color, #0a9d94));
    color:var(--app-header-text-color, #fff);
    box-shadow:0 2px 4px rgba(0,0,0,.15); }
  .menubtn { border:0; background:transparent; color:inherit; cursor:pointer;
    width:44px; height:44px; border-radius:50%; display:grid; place-items:center; }
  .menubtn:hover { background:rgba(255,255,255,.12); }
  .tbtitle { font-size:18px; font-weight:600; }
  #root { max-width:640px; margin:0 auto; padding:26px 18px 48px;
    color:var(--primary-text-color); font-family:var(--paper-font-body1_-_font-family, sans-serif); }
  .pagehead { display:flex; align-items:center; justify-content:space-between; gap:12px; }
  .eyebrow { font-size:11px; letter-spacing:.2em; text-transform:uppercase;
    color:var(--chihiros-accent); font-weight:700; }
  h1 { font-size:23px; font-weight:700; margin:2px 0 0; }
  .switch, .switcher { display:flex; gap:6px; flex-wrap:wrap; }
  .switch button { border:1px solid var(--divider-color); background:var(--card-background-color);
    color:var(--secondary-text-color); border-radius:999px; padding:6px 12px; font-size:12.5px;
    font-weight:600; cursor:pointer; }
  .switch button.on { border-color:var(--chihiros-accent); color:var(--primary-text-color); }
  .statusline { display:flex; align-items:center; gap:10px; margin:16px 0 20px;
    font-size:13.5px; color:var(--secondary-text-color); flex-wrap:wrap; }
  .statusline b { color:var(--primary-text-color); font-weight:600; }
  .dot { color:var(--divider-color); }
  .led { width:9px; height:9px; border-radius:50%; flex:none; }
  .card { background:var(--card-background-color); border:1px solid var(--divider-color);
    border-radius:16px; padding:20px; box-shadow:var(--ha-card-box-shadow,none); }
  .card + .card { margin-top:14px; }
  .curvehead { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:12px; }
  .ct { font-weight:600; font-size:14px; }
  canvas { width:100%; display:block; }
  .bright { display:flex; align-items:baseline; gap:8px; margin-top:14px; }
  .big { font-size:32px; font-weight:700; line-height:1; }
  .u { color:var(--secondary-text-color); font-size:14px; }
  .chrow { display:flex; gap:8px; margin-top:12px; }
  .ch { flex:1; background:var(--secondary-background-color); border-radius:11px; padding:8px 0; text-align:center; }
  .ch .n { font-weight:700; font-size:14px; }
  .ch .c { font-size:10px; letter-spacing:.12em; color:var(--secondary-text-color); margin-top:2px; }
  .confirm { margin-top:12px; font-size:12.5px; font-weight:600; }
  .confirm.ok { color:var(--success-color,#0f9d7a); }
  .confirm.unk { color:var(--warning-color,#d9971f); }
  .confirm.pending { color:var(--chihiros-accent); display:flex; align-items:center; gap:8px; }
  .spin { width:12px; height:12px; border-radius:50%; display:inline-block;
    border:2px solid color-mix(in srgb, var(--chihiros-accent) 30%, transparent);
    border-top-color:var(--chihiros-accent); animation:spin .7s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion:reduce) { .spin { animation:none; } }
  .lbl { font-weight:600; font-size:13px; margin-bottom:12px; }
  .progs { display:flex; gap:8px; flex-wrap:wrap; }
  .prog { border:1px solid var(--divider-color); background:var(--secondary-background-color);
    color:var(--secondary-text-color); border-radius:999px; padding:8px 14px; font-size:12.5px;
    font-weight:600; cursor:pointer; }
  .prog.on { border-color:var(--chihiros-accent); color:var(--primary-text-color);
    background:color-mix(in srgb, var(--chihiros-accent) 14%, transparent); }
  .dev { display:flex; align-items:center; gap:12px; padding:12px 0; }
  .dev + .dev { border-top:1px solid var(--divider-color); }
  .dev .nm { flex:1; font-weight:600; font-size:14px; }
  .dev .st { font-size:11px; font-weight:700; }
  .dev .meta { font-size:11px; color:var(--secondary-text-color); }
  .btns { display:flex; gap:10px; margin-top:18px; }
  .btn { flex:1; border:1px solid var(--divider-color); background:var(--card-background-color);
    color:var(--primary-text-color); font-weight:600; font-size:13.5px; padding:12px; border-radius:12px;
    cursor:pointer; }
  .btn.danger { border-color:var(--error-color,#d8434f); color:var(--error-color,#d8434f); }
  .muted { color:var(--secondary-text-color); }
  .mono { font-family:monospace; }
  .foot { margin-top:22px; text-align:center; font-size:11px; color:var(--secondary-text-color); }
  .pvbtns { display:flex; gap:8px; }
  .preview { border:1px solid var(--chihiros-accent); background:transparent;
    color:var(--chihiros-accent); font:inherit; font-weight:600; font-size:12.5px;
    padding:5px 12px; border-radius:999px; cursor:pointer; white-space:nowrap; }
  .preview:hover { background:color-mix(in srgb, var(--chihiros-accent) 12%, transparent); }
  .preview.onlamp { border-color:var(--warning-color,#d9971f); color:var(--warning-color,#d9971f); }
  .preview.onlamp:hover { background:color-mix(in srgb, var(--warning-color,#d9971f) 14%, transparent); }
  .grouplbl { font-size:11px; letter-spacing:.04em; color:var(--secondary-text-color);
    margin:14px 0 8px; font-weight:600; }
  .grouplbl:first-of-type { margin-top:4px; }
  .collhead { display:flex; align-items:center; justify-content:space-between;
    margin-top:16px; padding-top:14px; border-top:1px solid var(--divider-color);
    cursor:pointer; font-size:13px; font-weight:600; color:var(--primary-text-color);
    user-select:none; }
  .collhead .chev { color:var(--secondary-text-color); font-size:12px; }
  [hidden] { display:none !important; }
  .tankedit { margin-top:12px; }
  .tankrow { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
  .tankname { flex:1; font-size:13px; font-weight:600; }
  .tankinput { font:inherit; font-size:13px; padding:7px 10px; border-radius:8px;
    border:1px solid var(--divider-color); background:var(--secondary-background-color);
    color:var(--primary-text-color); min-width:120px; }
  .btn.maint { width:100%; margin-top:14px; border-color:var(--divider-color); }
  .btn.maint.on { border-color:var(--chihiros-accent); color:var(--chihiros-accent);
    background:color-mix(in srgb, var(--chihiros-accent) 12%, transparent); }
  .sched { display:flex; flex-direction:column; gap:14px; margin-top:14px; }
  .sunrow { display:flex; align-items:center; gap:9px; font-size:13.5px; font-weight:600;
    cursor:pointer; color:var(--primary-text-color); }
  .sunrow input { width:18px; height:18px; accent-color:var(--chihiros-accent); cursor:pointer; }
  .fields { display:flex; gap:18px; flex-wrap:wrap; }
  .field.dim { opacity:.5; }
  .sunnote { font-size:12px; color:var(--secondary-text-color); }
  .field { display:flex; flex-direction:column; gap:8px; flex:1; min-width:150px;
    font-size:12.5px; font-weight:600; color:var(--secondary-text-color); }
  .field b { color:var(--primary-text-color); font-family:monospace; }
  .field input[type=time] { font:inherit; font-size:15px; padding:8px 10px;
    border:1px solid var(--divider-color); border-radius:9px;
    background:var(--secondary-background-color); color:var(--primary-text-color); }
  .field input[type=range] { width:100%; accent-color:var(--chihiros-accent); }
  .toast { position:fixed; left:50%; bottom:24px; transform:translate(-50%,20px);
    background:var(--primary-text-color); color:var(--card-background-color);
    padding:10px 18px; border-radius:10px; font-size:13.5px; font-weight:600;
    opacity:0; pointer-events:none; transition:opacity .2s, transform .2s; z-index:10;
    box-shadow:0 6px 24px rgba(0,0,0,.3); max-width:90vw; }
  .toast.show { opacity:1; transform:translate(-50%,0); }
  .toast.ok { background:var(--success-color,#0f9d7a); color:#fff; }
  .toast.warn { background:var(--warning-color,#d9971f); color:#fff; }
  .toast.error { background:var(--error-color,#d8434f); color:#fff; }
`;

customElements.define("chihiros-panel", ChihirosPanel);
