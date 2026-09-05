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
// Programs grouped by purpose. The flat PROGRAMS list is derived for lookups.
const PROGRAM_GROUPS = [
  ["🌱 Daily", [
    ["natural_day", "Natural Day"], ["plant_growth", "Plant Growth"],
    ["low_tech", "Low Tech"], ["high_tech", "High Tech"],
    ["siesta", "Siesta"], ["cloudy_day", "Cloudy Day"],
    ["plant_recovery", "Plant Recovery"],
  ]],
  ["🌙 Night", [["moonlight", "Moonlight"]]],
  ["🧳 Away", [["vacation", "Vacation"]]],
  ["⬛ Treatments", [
    ["algae_protection_early", "Algae Protection"], ["blackout", "Blackout"],
  ]],
];
const PROGRAMS = PROGRAM_GROUPS.flatMap(([, items]) => items);
// Programs that can be run as a bounded treatment -> default number of days.
const TREATMENTS = { blackout: 3, algae_protection_early: 7 };
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
    this._collapsed = { program: true, setup: true, schedule: true, tanks: true, co2: true };
    this._wiz = null;              // first-time setup wizard state (null = not in it)
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
    clearTimeout(this._retryTimer);
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
    clearTimeout(this._retryTimer);   // a fresh load supersedes any pending retry
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
      if (!this._selected || !this._tanks[this._selected]) {
        // Restore the last-selected tank (per browser); fall back to the first.
        let remembered = null;
        try { remembered = localStorage.getItem("aqua_chihiros_tank"); } catch (e) { /* ignore */ }
        this._selected = (remembered && this._tanks[remembered]) ? remembered : (names[0] || null);
      }
      const leader = this._leader();
      if (leader) {
        this._curve = await this._ws({ type: "aqua_chihiros/get_curve", entry_id: leader.entry_id });
      }
      if (!this._switches) {
        try {
          const r = await this._ws({ type: "aqua_chihiros/list_switches" });
          this._switches = r.switches || [];
        } catch (e) { this._switches = []; }
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
    this._collapsed.program = true;   // collapse back to show just the active one
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
       <svg class="tblogo" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path fill="currentColor" d="M 8.19896966792,7.12526481776 l 0.227642583824,0.265203610155 l 1.56504276379,-0.0125203421103 l 0.560000756208,-0.800163682143 l -2.35268610382,0.547480414098 Z M 7.43636701211,8.88835662948 c -0.0830895430959,-0.0193496196251 -0.16845551203,-0.0341463875737 -0.252683268045,-0.0432520909266 c 0.747805887863,0.717074139047 1.64813230689,1.25203421103 2.63041005609,1.56618097671 c 0.229919009663,0.0705692009855 0.465529083921,0.135447337375 0.704553796936,0.186666918736 c -0.799025469223,-0.915123186974 -1.88943344574,-1.52065245995 -3.08228058498,-1.71073401744 M 5.78026721478,7.98233914586 l -0.744391249106,0.217398667552 l 0.743253036187,-0.217398667552 l 0.00113821291912,0 Z M 20.5428887758,10.5877085177 c -0.498537258575,-0.167317299111 -1.01414771094,-0.274309313508 -1.53658744081,-0.322114256111 c -0.910570335297,-0.0796749043385 -1.82455530935,-0.105853801478 -2.73854028341,-0.0808131172576 c 0.0432520909266,0.237886500096 0.0762602655812,0.474634787274 0.0990245239636,0.717074139047 c 0.283415016861,0.0204878325442 0.565691820804,0.0386992392501 0.846830411827,0.0682927751473 c 0.629431744274,0.0489431555222 1.25203421103,0.173008363707 1.85414884525,0.367642772876 c 0.610082124649,0.200325473765 1.16780645502,0.533821859068 1.63561196478,0.976586684606 l -0.120650569427,0.125203421103 c -0.903741057783,-0.860488966856 -2.17057203677,-1.1370747062 -3.39187449898,-1.22471710098 c -0.264065397236,-0.0182114067059 -0.528130794472,-0.0341463875737 -0.789919765871,-0.0386992392501 c -0.162764447434,-0.00910570335297 -0.319837830273,-0.0136585550295 -0.480325851869,-0.0136585550295 c -0.234471861339,-0.00796749043385 -0.468943722678,-0.00796749043385 -0.703415584017,-0.00796749043385 c -0.144553040728,-0.00455285167649 -0.286829655619,-0.00455285167649 -0.435935548024,-0.00455285167649 c -0.441626612619,0 -0.879838586481,0.00455285167649 -1.32260341202,0.00455285167649 l -0.316423191516,0 c -0.204878325442,0.00341463875736 -0.406342012126,0.00341463875736 -0.613496763407,0.00341463875736 l -0.00341463875737,0 c -0.316423191516,0 -0.630569957193,-0.00341463875736 -0.946993148709,-0.0295935358972 c -0.037561026331,-0.00455285167649 -0.0717074139047,-0.00455285167649 -0.111544866074,-0.0102439162721 c -0.200325473765,-0.0125203421103 -0.406342012126,-0.0386992392501 -0.607805698811,-0.0728456268238 c -0.20715475128,-0.0239024713016 -0.413171289641,-0.0603252847135 -0.616911402164,-0.110406653155 c -0.182114067059,-0.0386992392501 -0.364228134119,-0.0876423947724 -0.547480414098,-0.140000189052 c -1.21219675886,-0.356260643685 -2.30715758706,-1.02894447889 -3.17789047019,-1.95203515629 c -0.218536880471,0.00341463875736 -0.487155129384,0.0113821291912 -0.804716533819,0.0159349808677 c -0.589594292105,0.00910570335297 -0.86845645729,-0.101300949802 -1.03349733056,-0.327805320707 l 0.623740679679,-0.175284789545 l 0.530407220311,-0.151382318243 l -0.0694309880664,-0.0819513301768 l -0.720488777804,0.0830895430959 l -0.00341463875736,-0.00682927751473 l 0,0.00455285167649 l -0.49284619398,0.0569106459561 c -0.104715588559,-0.0318699617354 -0.201463686685,-0.0887806076915 -0.277723952266,-0.16845551203 c -0.241301138854,-0.33691102406 -0.343740301575,-0.756911591216 -0.282276803942,-1.16780645502 l 0.00910570335297,-0.196910835008 l 0.191219770412,-0.0273171100589 c 0.417724141318,-0.0694309880664 2.35268610382,-0.379024902068 2.8751258337,-0.442764825538 l 0.437073760943,-0.499675471494 l 1.37837584506,-0.211707602957 l 0.00682927751473,0 c 0.248130416369,-0.468943722678 0.550895052855,-0.90715569654 0.903741057783,-1.29983915364 c 0.789919765871,-0.684065964392 1.62650626142,-1.31122128283 2.50293020915,-1.87691310363 c 0.178699428302,-0.136585550295 -0.0489431555222,0.566830033723 -0.605529272973,0.991383452555 c -0.478049426031,0.340325662817 -0.937887445356,0.704553796936 -1.37837584506,1.09382261528 c -0.228780796743,0.248130416369 -0.412033076722,0.534960071987 -0.54406577534,0.845692198907 c 0.203740112523,-0.128618059861 0.420000567156,-0.237886500096 0.645366725142,-0.322114256111 c 0.31073212692,-0.11723593067 0.638537447627,-0.193496196251 0.969757407092,-0.225366157986 c 0.118374143589,-0.0102439162721 0.239024713016,-0.0113821291912 0.357398856604,-0.00341463875737 c 0.37561026331,-0.343740301575 0.789919765871,-0.640813873466 1.23496101725,-0.886667863996 c 0.970895620011,-0.379024902068 1.96569371132,-0.690895241907 2.97870320934,-0.929919954922 c 0.213984028795,-0.0694309880664 -0.232195435501,0.514472239443 -0.898049993187,0.731870906995 c -0.562277182046,0.159349808677 -1.11658687366,0.35056957909 -1.65837622316,0.572521098318 c -0.299349997729,0.157073382839 -0.57024467248,0.367642772876 -0.796749043385,0.62146425384 l 0.00682927751473,0 c 0.322114256111,0.0876423947724 0.63512280887,0.213984028795 0.929919954922,0.373333837472 c 1.99756367306,1.0892697636 2.90927222128,0.911708548217 2.91268686003,0.90715569654 l 0.556586117451,-0.136585550295 l -0.294797146053,0.49284619398 c -0.282276803942,0.49284619398 -0.752358739539,0.847968624746 -1.30325379239,0.977724897526 c 0.361951708281,0.709106648613 0.624878892598,1.46488002691 0.781952275437,2.24569408943 c 0.958375277901,0.0193496196251 1.91447412996,0.0944716722871 2.86602013035,0.226504370905 c 0.539512923664,0.0785366914194 1.07105835689,0.218536880471 1.57983953174,0.418862354237 c 0.508781174847,0.213984028795 0.970895620011,0.522439729877 1.36471729003,0.910570335297 l -0.10357737564,0.113821291912 c -0.393821670016,-0.353984217847 -0.851383263503,-0.627155318436 -1.3453676704,-0.806992959657 M 2.86302750308,12.4987680089 l 0.00227642583824,0 c -0.258374332641,1.06081444062 -0.198049047927,2.17512488844 0.170731937868,3.20293115441 c 0.0648781363899,0.195772622089 0.160488021596,0.379024902068 0.283415016861,0.545203988259 l 0.0113821291912,0.0159349808677 l 0,0.00682927751473 c 0.00910570335297,0.0102439162721 0.0159349808677,0.0193496196251 0.0250406842207,0.0295935358972 c 0.218536880471,0.328943533626 0.507642961928,0.605529272973 0.844553985988,0.808131172576 c 1.1666682421,0.878700373562 2.69414997956,1.66975835235 4.19089996821,1.36471729003 c 0.0421138780075,-0.00796749043385 0.0830895430959,-0.0216260454633 0.125203421103,-0.0318699617354 c 0.42796805759,-0.128618059861 0.833171856797,-0.323252469031 1.20309105551,-0.578212162914 c -2.59740188144,-2.2081330631 -4.45041251377,-3.14146765678 -5.50325946395,-2.76927203222 c -0.297073571891,0.110406653155 -0.538374710745,0.331219959464 -0.676098473958,0.616911402164 c -0.0227642583824,-0.046666729684 -0.0455285167649,-0.0956098852062 -0.0671545622282,-0.146829466567 c -0.0956098852062,-0.265203610155 -0.0580488588752,-0.562277182046 0.10357737564,-0.794472617547 c 0.361951708281,-0.516748665281 1.3453676704,-0.809269385496 2.44943420195,-0.332358172384 c 1.36813192878,0.67382204812 2.6429303982,1.53203458914 3.78683438192,2.54845872591 c 0.162764447434,0.138861976133 0.325528894869,0.27203288767 0.486016916465,0.40178916045 c 0.109268440236,-0.106992014397 0.212845815876,-0.21967509339 0.309593914001,-0.339187449898 c -0.167317299111,-0.133170911537 -0.332358172384,-0.270894674751 -0.498537258575,-0.413171289641 c -1.18032679713,-1.04601767267 -2.49268629288,-1.92585625915 -3.90407031259,-2.6190279269 c -1.33967660581,-0.577073949995 -2.52341804169,-0.191219770412 -3.0003292548,0.489431555222 c -0.0694309880664,-0.792196191709 0,-1.59008344801 0.202601899604,-2.35837716842 c 1.7858560701,-0.90715569654 4.1430950256,0.615773189245 5.57610509078,1.58894523509 c 0.73870018451,0.500813684414 1.44553040728,1.04601767267 2.14211671379,1.59918915137 c 0.0876423947724,0.0682927751473 0.16845551203,0.134309124456 0.249268629288,0.195772622089 c 0.135447337375,-0.423415205913 0.219675093391,-0.861627179775 0.251545055126,-1.30553021823 l 0,-0.0318699617354 c 0.0307317488163,-0.443903038457 0.00682927751473,-0.888944289834 -0.0694309880664,-1.3271562637 c -0.0546342201178,-0.316423191516 -0.141138401971,-0.626017105517 -0.258374332641,-0.925367103246 l -0.00910570335297,-0.0182114067059 c -0.0250406842207,-0.0648781363899 -0.0489431555222,-0.126341634023 -0.0773984785003,-0.191219770412 c -0.0136585550295,-0.0273171100589 -0.0273171100589,-0.055772433037 -0.0386992392501,-0.0865041818533 c -0.0113821291912,-0.0295935358972 -0.0318699617354,-0.0603252847135 -0.0489431555222,-0.0956098852062 c 0.182114067059,0.0250406842207 0.368780985795,0.0443903038458 0.55772433037,0.0591870717943 c 0.374472050391,0.0216260454633 0.838862921393,0.0250406842207 1.19170892632,0.0193496196251 l 0.550895052855,0 c 0.493984406899,-0.0227642583824 1.00276558175,-0.0227642583824 1.45805074939,-0.0136585550295 c 0.0523577942796,1.24065208184 -0.105853801478,2.48130416369 -0.46666729684,3.66959845125 c -0.344878514494,1.1905707134 -0.999350942989,2.26504370905 -1.8928480845,3.11415054672 c -0.11723593067,0.106992014397 -0.242439351773,0.211707602957 -0.372195624553,0.31073212692 c -0.429106270509,0.331219959464 -0.898049993187,0.602114634215 -1.3988636776,0.805854746738 c -0.490569768141,0.200325473765 -0.999350942989,0.353984217847 -1.51723782119,0.462114445163 c -2.02943363479,0.437073760943 -4.14764787728,0.0887806076915 -5.93578037322,-0.975448471687 l -0.046666729684,-0.0307317488163 c -1.84618135482,-1.17577394545 -2.40732032394,-3.63772848951 -1.25431063687,-5.50895052855 c 0.231057222582,-0.365366347038 0.521301516958,-0.689757028988 0.857074328099,-0.957237064981 M 7.52173298104,20.6108114835 c 0.659025280171,-0.00113821291912 1.31805056034,-0.075122052662 1.96000264673,-0.22081330631 c 0.493984406899,-0.111544866074 0.980001323364,-0.262927184317 1.45122147188,-0.45414695473 c 0.594147143782,-0.240162925935 1.15073326123,-0.57024467248 1.65040873273,-0.977724897526 c 0.126341634023,-0.10357737564 0.249268629288,-0.212845815876 0.3630899212,-0.322114256111 c 0.890082502753,-0.8809767994 1.54569314417,-1.97707584051 1.90309200077,-3.18358153478 c 0.377886689148,-1.238375656 0.547480414098,-2.53252374505 0.500813684414,-3.82667183409 c 0.46666729684,0.0159349808677 0.833171856797,0.037561026331 0.997074517151,0.0500813684414 l 0.0944716722871,0 l 0,0.00910570335297 c 0.112683078993,1.42959542642 -0.0227642583824,2.86602013035 -0.397236308773,4.24781061416 l 0.00341463875737,0 s -0.0295935358972,0.112683078993 -0.0978863110445,0.306179275244 c -0.0717074139047,0.218536880471 -0.149105892405,0.432520909266 -0.234471861339,0.63512280887 c -0.163902660354,0.384715966663 -0.361951708281,0.753496952459 -0.590732505024,1.10292831863 c 2.56211728094,0.95951349082 4.53464026978,0.140000189052 6.27269139728,-0.591870717943 c 0.306179275244,-0.126341634023 0.598699995458,-0.249268629288 0.878700373562,-0.356260643685 c 0.0887806076915,-0.0341463875737 0.190081557493,-0.0125203421103 0.254959693883,0.0569106459561 c 0.0660163493091,0.0682927751473 0.0865041818533,0.169593724949 0.0523577942796,0.258374332641 c -0.0705692009855,0.170731937868 -0.150244105324,0.338049236979 -0.240162925935,0.500813684414 c -2.55756442927,2.77837773558 -5.61708075587,2.50975948666 -8.19171837892,1.38975797425 c -0.109268440236,0.11723593067 -0.223089732148,0.235610074258 -0.343740301575,0.351707792009 c 1.19853820384,0.575935737076 2.50293020915,0.888944289834 3.83122468576,0.92081425157 c 1.23040816557,0.00796749043385 2.43691385984,-0.344878514494 3.47382582916,-1.01642413678 c -0.573659311237,0.575935737076 -1.25886348855,1.02325341429 -2.01236044101,1.31691234742 c -0.651057789738,0.248130416369 -1.34195303164,0.372195624553 -2.03740112523,0.367642772876 c -1.36244086419,-0.0432520909266 -2.69528819248,-0.398374521693 -3.89951746091,-1.03918839516 c -0.901464631944,0.685204177311 -1.94748230462,1.14959504831 -3.05610168784,1.36016443835 l 0,-0.00341463875737 c -2.60878401063,0.525854368634 -5.30407220311,-0.29821178481 -7.18553815842,-2.19902735974 c 0.046666729684,0.0318699617354 0.093333459368,0.0637399234708 0.141138401971,0.093333459368 c 1.3453676704,0.811545811334 2.88650796289,1.23723744309 4.45496536544,1.22699352681"/></svg>
       <span class="tbtitle">AquaChihiros</span>`;
    const m = this.shadowRoot.getElementById("menu");
    if (m) m.addEventListener("click", () =>
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })));
  }

  _errText(err) {
    if (!err) return "";
    if (typeof err === "string") return err;
    if (err.message) return err.message;
    if (err.error) return err.error;
    if (err.code) return "code: " + err.code;
    try { return JSON.stringify(err); } catch (e) { return String(err); }
  }

  // Not a hard error: the integration may still be starting up (after a
  // restart/reload). Show a calm "connecting" state and retry automatically.
  _renderError(err) {
    this._syncTopbar();
    const detail = this._errText(err);
    this.shadowRoot.getElementById("root").innerHTML =
      `<div class="pagehead"><div class="eyebrow">Aquarium light</div><h1>AquaChihiros</h1></div>
       <section class="card">
         <div class="confirm pending"><span class="spin"></span>Connecting to AquaChihiros…</div>
         <p class="muted" style="margin:10px 0 0;font-size:12.5px">The integration may still be starting up. Retrying…</p>
         ${detail ? `<p class="mono" style="font-size:11px;color:var(--ink-3);margin-top:8px">${detail}</p>` : ""}
       </section>`;
    clearTimeout(this._retryTimer);
    this._retryTimer = setTimeout(() => this._load(), 3000);
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
    // First-time setup: a freshly added lamp shows a guided wizard instead of
    // the full controls until the user finishes (or skips) it.
    if (dev.onboarded === false) { this._renderWizard(dev); return; }
    root.innerHTML = `
      <div class="head">
        <div>
          <h1>${esc(this._selected)}</h1>
          <div class="subline"><span class="led" style="background:${CONN_COLOR[dev.connection]}"></span>${CONN_LABEL[dev.connection] || dev.connection}${this._members().length > 1 ? ` · ${this._members().length} lamps` : ""}${dev.rssi != null ? ` · <span class="mono">${dev.rssi} dBm</span>` : ""}</div>
        </div>
        ${Object.keys(this._tanks).length > 1 ? this._switcher() : ""}
      </div>

      ${dev.treatment ? `
      <section class="card treatment">
        <div class="trow">
          <span class="tmark">🩹</span>
          <div class="tinfo">
            <b>${esc(dev.treatment.name)} treatment active</b>
            <span class="muted">Day ${dev.treatment.day} of ${dev.treatment.total_days} · then reverts to ${esc(dev.treatment.revert_to)}</span>
          </div>
          <button class="btn small" id="stoptreat">Stop</button>
        </div>
        <div class="tbar"><span style="width:${Math.round((dev.treatment.progress || 0) * 100)}%"></span></div>
      </section>` : ""}

      <section class="card hero">
        <div class="herotop">
          <span class="now">
            <span class="badge">● LIVE</span>
            <span class="phase">${esc(dev.program_name)} <small>· ${esc(dev.phase)}</small></span>
          </span>
          <button class="preview" id="preview">▶ Preview</button>
        </div>
        <div class="curvewrap">
          <canvas id="curve" width="1160" height="240"></canvas>
          <div id="hovertip" class="hovertip" hidden></div>
        </div>
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

      <section class="card ctlcard">
        <div class="ctl" data-collapse="program">
          <span class="ic">🌱</span>
          <span class="ctxt"><small>Program</small><b>${esc(dev.program_name)}</b></span>
          <span class="go">${this._collapsed.program ? "Change ›" : "Close ▾"}</span>
        </div>
        <div class="progopts" ${this._collapsed.program ? "hidden" : ""}>
          ${PROGRAM_GROUPS.map(([label, items]) => `
            <div class="grouplbl">${label}</div>
            <div class="progs">
              ${items.map(([k, n]) => `<button class="prog ${k === dev.program_key ? "on" : ""}" data-prog="${k}">${n}</button>`).join("")}
            </div>`).join("")}
          ${TREATMENTS[dev.program_key] && !dev.treatment ? `
            <div class="treatstart">
              <span class="muted">Run as timed treatment:</span>
              <input type="number" id="treatdays" min="1" max="14" value="${TREATMENTS[dev.program_key]}">
              <span class="muted">days</span>
              <button class="btn small" id="starttreat">▶ Start</button>
            </div>` : ""}
        </div>
      </section>

      <section class="card ctlcard">
        <div class="ctl maint" id="maint">
          <span class="ic">🧽</span>
          <span class="ctxt"><small>Maintenance</small><b>${dev.maintenance ? "On · white 100%" : "Off"}</b></span>
          <span class="go">${dev.maintenance ? "Stop ›" : "Start ›"}</span>
        </div>
      </section>

      <section class="card devices">
        ${this._members().map((d) => this._lampRow(d)).join("")}
        <div class="util">
          <button id="reconnect">⟳ Reconnect</button>
          <button class="off" id="off">⏻ Turn off</button>
        </div>
      </section>

      <section class="card ctlcard">
        <div class="setrow" data-collapse="setup">
          <span class="ic">⚙️</span>
          <span class="ctxt"><b>Setup</b><small>Schedule · CO₂ · tanks &amp; lamps</small></span>
          <span class="chev">${this._collapsed.setup ? "›" : "▾"}</span>
        </div>
        ${!this._collapsed.setup ? `
          <div class="setbody">
            <div class="setrow sub" data-collapse="schedule">
              <span class="ic">🌇</span>
              <span class="ctxt"><b>Schedule &amp; timing</b><small>${this._scheduleValue(dev)}</small></span>
              <span class="chev">${this._collapsed.schedule ? "›" : "▾"}</span>
            </div>
            ${!this._collapsed.schedule ? `<div class="subbody">${this._scheduleContent(dev)}</div>` : ""}
            <div class="setrow sub" data-collapse="co2">
              <span class="ic">🫧</span>
              <span class="ctxt"><b>CO₂</b><small>${this._co2Value(dev)}</small></span>
              <span class="chev">${this._collapsed.co2 ? "›" : "▾"}</span>
            </div>
            ${!this._collapsed.co2 ? `<div class="subbody">${this._co2Content(dev)}</div>` : ""}
            <div class="setrow sub" data-collapse="tanks">
              <span class="ic">🐟</span>
              <span class="ctxt"><b>Tanks &amp; lamps</b><small>${this._tankValue()}</small></span>
              <span class="chev">${this._collapsed.tanks ? "›" : "▾"}</span>
            </div>
            ${!this._collapsed.tanks ? `<div class="subbody">${this._tankContent()}</div>` : ""}
          </div>` : ""}
      </section>

      <div class="foot mono">Local Bluetooth · no cloud · schedule stored on lamp</div>`;

    this.shadowRoot.querySelectorAll("[data-prog]").forEach((b) =>
      b.addEventListener("click", () => this._setProgram(b.dataset.prog)));
    this.shadowRoot.querySelectorAll("[data-sel]").forEach((b) =>
      b.addEventListener("click", () => {
        this._selected = b.dataset.sel;
        try { localStorage.setItem("aqua_chihiros_tank", this._selected); } catch (e) { /* ignore */ }
        this._load();
      }));
    const offBtn = this.shadowRoot.getElementById("off");
    if (offBtn) offBtn.addEventListener("click", () => this._emergencyOff());
    const rc = this.shadowRoot.getElementById("reconnect");
    if (rc) rc.addEventListener("click", () => this._reconnect());

    this.shadowRoot.querySelectorAll("[data-tank]").forEach((inp) =>
      inp.addEventListener("change", () => this._setTank(inp.dataset.tank, inp.value.trim())));

    const co2apply = () => {
      const sw = this.shadowRoot.getElementById("co2-switch").value || null;
      const on = parseInt(this.shadowRoot.getElementById("co2-on").value, 10) || 0;
      const off = parseInt(this.shadowRoot.getElementById("co2-off").value, 10) || 0;
      this._setCo2(sw, on, off);
    };
    ["co2-switch", "co2-on", "co2-off"].forEach((id) => {
      const el = this.shadowRoot.getElementById(id);
      if (el) el.addEventListener("change", co2apply);
    });

    const maint = this.shadowRoot.getElementById("maint");
    if (maint) maint.addEventListener("click", () => this._setMaintenance(!this._dev().maintenance));

    const startTreat = this.shadowRoot.getElementById("starttreat");
    if (startTreat) startTreat.addEventListener("click", () => {
      const days = parseFloat(this.shadowRoot.getElementById("treatdays").value) || 3;
      this._startTreatment(this._dev().program_key, days);
    });
    const stopTreat = this.shadowRoot.getElementById("stoptreat");
    if (stopTreat) stopTreat.addEventListener("click", () => this._stopTreatment());

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
    this._bindCurveHover(dev);
  }

  // Scrub the timeline: hovering (or dragging on touch) shows the time and the
  // channel values at the pointer; leaving restores the live "now" readout.
  _bindCurveHover(dev) {
    const cv = this.shadowRoot.getElementById("curve");
    const tip = this.shadowRoot.getElementById("hovertip");
    if (!cv || !tip || !this._curve) return;
    const titleEl = this.shadowRoot.getElementById("pv-title");
    const at = (e) => {
      if (this._playing) return;                 // don't fight the preview player
      const rect = cv.getBoundingClientRect();
      const px = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
      const frac = Math.max(0, Math.min(1, px / rect.width));
      const minute = frac * 1440;
      this._drawCurve(minute);
      this._updateReadout(minute, null);         // update values, keep the title
      tip.hidden = false;
      tip.textContent = minToTime(Math.round(minute));
      // Keep the bubble inside the card, pointing at the cursor.
      const x = Math.max(24, Math.min(rect.width - 24, px));
      tip.style.left = `${x}px`;
    };
    const leave = () => {
      if (this._playing) return;
      tip.hidden = true;
      this._drawCurve();                          // back to the live "now" marker
      const b = this.shadowRoot.getElementById("pv-b");
      if (b) b.textContent = dev.brightness;
      for (let i = 0; i < 4; i++) {
        const el = this.shadowRoot.getElementById(`pv-ch-${i}`);
        if (el) el.textContent = dev.desired[i];
      }
      if (titleEl) titleEl.innerHTML = `${esc(dev.program_name)} <small>· ${esc(dev.phase)}</small>`;
    };
    cv.addEventListener("mousemove", at);
    cv.addEventListener("mouseleave", leave);
    cv.addEventListener("touchstart", at, { passive: true });
    cv.addEventListener("touchmove", at, { passive: true });
    cv.addEventListener("touchend", leave);
  }

  async _startTreatment(program, days) {
    this._lastInteraction = Date.now();
    this._toast(`Starting treatment (${days} days)…`);
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/start_treatment", entry_id: id, program, days }));
    } catch (err) { this._toast("Could not start treatment", "error"); }
    await this._load();
  }

  async _stopTreatment() {
    this._lastInteraction = Date.now();
    this._toast("Stopping treatment…");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/stop_treatment", entry_id: id }));
    } catch (err) { this._toast("Could not stop", "error"); }
    await this._load();
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

  // -- first-time setup wizard ----------------------------------------------
  _renderWizard(dev) {
    if (!this._wiz) {
      this._wiz = {
        step: "intro",
        mode: null,
        tank: this._selected || dev.name,
        program: dev.program_key || "plant_growth",
        follow_sun: dev.follow_sun !== false,
        start: minToTime(dev.start_minute),
        len: dev.day_length_minutes / 60,
        co2: (dev.co2 && dev.co2.switch) || "",
      };
    }
    const w = this._wiz;
    const total = w.mode === "advanced" ? 5 : 3;
    const dots = (active) => `<div class="wsteps">${
      Array.from({ length: total }, (_, i) =>
        `<i class="${i < active ? "done" : i === active ? "on" : ""}"></i>`).join("")}</div>`;
    const nav = (back, next, nextLabel) => `
      <div class="wnav">
        ${back ? `<button class="wback" data-go="${back}">← Back</button>` : ""}
        <span class="wsp"></span>
        <button class="wbtn" data-go="${next}"${next === "__apply" ? ' id="wiz-apply"' : ""}>${nextLabel}</button>
      </div>`;

    let body;
    if (w.step === "intro") {
      body = `
        <div class="weyebrow">Welcome</div>
        <h2 class="wh">Let's set up your lamp</h2>
        <p class="wlead">Your new Chihiros lamp was found. Choose how much to set up
          now — you can change everything later.</p>
        <div class="wpaths">
          <button class="wpath" data-mode="basic">
            <span class="wic">⚡</span>
            <span class="wtt"><b>Quick</b><small>Name the tank and pick a program. Done in 20 seconds.</small></span>
            <span class="wgo">›</span></button>
          <button class="wpath" data-mode="advanced">
            <span class="wic">⚙️</span>
            <span class="wtt"><b>Advanced</b><small>Also set the light schedule / follow sunset and link CO₂.</small></span>
            <span class="wgo">›</span></button>
        </div>
        <p class="wdisclaimer">Not affiliated with Chihiros. “Chihiros” and its logos are
          trademarks of their respective owners; this is an independent, unofficial integration.</p>`;
    } else if (w.step === "tank") {
      body = `${dots(0)}
        <div class="weyebrow">Step 1 · Tank</div>
        <h2 class="wh">What's this aquarium called?</h2>
        <p class="wlead">The name shows at the top of the panel. Lamps sharing a tank
          name are controlled together.</p>
        <label class="wf"><span>Tank name</span>
          <input type="text" id="wiz-tank" value="${esc(w.tank)}" placeholder="e.g. Living room 60L"></label>
        ${nav("intro", "program", "Next")}`;
    } else if (w.step === "program") {
      const isLast = w.mode === "basic";
      body = `${dots(1)}
        <div class="weyebrow">Step 2 · Program</div>
        <h2 class="wh">Pick a light program</h2>
        <p class="wlead">This sets the colour and brightness curve across the day.
          <b>Plant Growth</b> is a good start for planted tanks.</p>
        ${PROGRAM_GROUPS.slice(0, 2).map(([label, items]) => `
          <div class="grouplbl">${label}</div>
          <div class="progs">${items.map(([k, n]) =>
            `<button class="prog ${k === w.program ? "on" : ""}" data-wprog="${k}">${n}</button>`).join("")}</div>`).join("")}
        ${nav("tank", isLast ? "review" : "schedule", isLast ? "Review" : "Next")}`;
    } else if (w.step === "schedule") {
      body = `${dots(2)}
        <div class="weyebrow">Step 3 · Schedule</div>
        <h2 class="wh">When are the lights on?</h2>
        <label class="sunrow"><input type="checkbox" id="wiz-fs" ${w.follow_sun ? "checked" : ""}>
          <span>🌇 Follow the real sunset</span></label>
        <div class="fields">
          <label class="field ${w.follow_sun ? "dim" : ""}"><span>Start time ${w.follow_sun ? "· auto" : ""}</span>
            <input type="time" id="wiz-start" value="${w.start}" ${w.follow_sun ? "disabled" : ""}></label>
          <label class="field"><span>Day length <b id="wiz-len-val">${w.len.toFixed(1)} h</b></span>
            <input type="range" id="wiz-len" min="1" max="14" step="0.5" value="${w.len}"></label>
        </div>
        <p class="sunnote">${w.follow_sun
          ? "Sunset is anchored to the sun; change the day length to shift the start."
          : "Manual window — start and end times are fixed."}</p>
        ${nav("program", "co2", "Next")}`;
    } else if (w.step === "co2") {
      const options = ['<option value="">— none (skip) —</option>'].concat(
        (this._switches || []).map((s) =>
          `<option value="${esc(s.entity_id)}" ${s.entity_id === w.co2 ? "selected" : ""}>${esc(s.name)}</option>`)
      ).join("");
      body = `${dots(3)}
        <div class="weyebrow">Step 4 · CO₂ <span class="muted" style="font-weight:400">· optional</span></div>
        <h2 class="wh">Link CO₂?</h2>
        <p class="wlead">Pick a switch that follows the photoperiod automatically
          (an hour before on, an hour before off). Changeable later.</p>
        <label class="wf"><span>CO₂ switch</span>
          <select id="wiz-co2">${options}</select></label>
        ${nav("schedule", "review", "Review")}`;
    } else if (w.step === "review") {
      const adv = w.mode === "advanced";
      const startMin = timeToMin(w.start);
      const span = `${minToTime(startMin)}–${minToTime(startMin + Math.round(w.len * 60))}`;
      const label = (PROGRAMS.find((p) => p[0] === w.program) || [null, w.program])[1];
      const rows = [
        ["Tank", esc(w.tank)], ["Program", esc(label)],
      ].concat(adv ? [
        ["Schedule", `${w.follow_sun ? "Follow sunset" : "Manual"} · ${w.len.toFixed(1)} h · ${span}`],
        ["CO₂", w.co2 ? "Linked" : "Not set"],
      ] : []);
      body = `${dots(adv ? 4 : 2)}
        <div class="weyebrow">Almost done</div>
        <h2 class="wh">Quick check</h2>
        <p class="wlead">Does this look right? You can change everything later in the panel.</p>
        <div class="wrev">${rows.map(([k, v]) =>
          `<div class="wr"><span>${k}</span><b>${v}</b></div>`).join("")}</div>
        ${nav(adv ? "co2" : "program", "__apply", "✓ Apply")}`;
    } else if (w.step === "applying") {
      body = `<div class="wcenter">
        <div class="confirm pending" style="justify-content:center"><span class="spin"></span>Setting up…</div></div>`;
    } else if (w.step === "done") {
      const label = (PROGRAMS.find((p) => p[0] === w.program) || [null, w.program])[1];
      body = `<div class="wcenter">
        <div class="wdone">✓</div>
        <h2 class="wh">Done — ${esc(w.tank)} is set up</h2>
        <p class="wlead">The <b>${esc(label)}</b> program is now running.</p>
        <button class="wbtn" data-go="__finish">Go to the panel →</button></div>`;
    }

    this.shadowRoot.getElementById("root").innerHTML = `<section class="card wcard">${body}</section>`;
    this._bindWizard();
  }

  _bindWizard() {
    const w = this._wiz;
    const r = this.shadowRoot;
    r.querySelectorAll("[data-mode]").forEach((b) =>
      b.addEventListener("click", () => { w.mode = b.dataset.mode; this._wizGo("tank"); }));
    r.querySelectorAll("[data-wprog]").forEach((b) =>
      b.addEventListener("click", () => { w.program = b.dataset.wprog; this._renderWizard(this._dev()); }));
    r.querySelectorAll("[data-go]").forEach((b) =>
      b.addEventListener("click", () => this._wizNav(b.dataset.go)));
    const fs = r.getElementById("wiz-fs");
    if (fs) fs.addEventListener("change", () => { w.follow_sun = fs.checked; this._renderWizard(this._dev()); });
    const len = r.getElementById("wiz-len");
    const lenVal = r.getElementById("wiz-len-val");
    if (len) len.addEventListener("input", () => { w.len = +len.value; if (lenVal) lenVal.textContent = `${w.len.toFixed(1)} h`; });
  }

  // Capture the current step's field values before navigating away.
  _wizCapture() {
    const w = this._wiz, r = this.shadowRoot;
    const tank = r.getElementById("wiz-tank"); if (tank) w.tank = tank.value.trim() || w.tank;
    const start = r.getElementById("wiz-start"); if (start) w.start = start.value || w.start;
    const co2 = r.getElementById("wiz-co2"); if (co2) w.co2 = co2.value;
  }

  _wizNav(go) {
    this._wizCapture();
    if (go === "__apply") { this._wizApply(); return; }
    if (go === "__finish") { this._wiz = null; this._load(); return; }
    this._wizGo(go);
  }

  _wizGo(step) { this._wiz.step = step; this._renderWizard(this._dev()); }

  async _wizApply() {
    const w = this._wiz;
    // Fix the target lamps up front: renaming the tank changes how _members()
    // resolves, so every command must go to these ids, not to a live lookup.
    const ids = this._memberIds();
    const send = (build) => Promise.allSettled(ids.map((id) => this._ws(build(id))));
    this._wizGo("applying");
    try {
      await send((id) => ({ type: "aqua_chihiros/set_tank", entry_id: id, tank: w.tank }));
      await send((id) => ({ type: "aqua_chihiros/set_program", entry_id: id, program: w.program }));
      if (w.mode === "advanced") {
        await send((id) => ({ type: "aqua_chihiros/set_follow_sun", entry_id: id, enabled: !!w.follow_sun }));
        await send((id) => ({ type: "aqua_chihiros/set_schedule", entry_id: id,
          start_minute: timeToMin(w.start), day_length_minutes: Math.round(w.len * 60) }));
        if (w.co2) {
          await send((id) => ({ type: "aqua_chihiros/set_co2", entry_id: id, switch: w.co2, before_on: 60, before_off: 60 }));
        }
      }
      await send((id) => ({ type: "aqua_chihiros/complete_onboarding", entry_id: id }));
      this._wizGo("done");
    } catch (err) {
      this._toast("Setup failed — try again", "error");
      this._wizGo("review");
    }
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

  _scheduleValue(dev) {
    const h = (dev.day_length_minutes / 60).toFixed(1);
    const span = `${minToTime(dev.start_minute)}–${minToTime(dev.start_minute + dev.day_length_minutes)}`;
    return dev.follow_sun ? `Follow sunset · ${h} h · ${span}` : `Manual · ${h} h · ${span}`;
  }

  _scheduleContent(dev) {
    return `
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
        : `<div class="sunnote">Manual: ${minToTime(dev.start_minute)}–${minToTime(dev.start_minute + dev.day_length_minutes)}.</div>`}`;
  }

  _co2Value(dev) {
    const c = dev.co2 || { enabled: false };
    if (!c.enabled) return "Not set — tap to link a switch";
    return c.on_at ? `On ${c.on_at}–${c.off_at} · currently ${c.on ? "on" : "off"}` : "No photoperiod in this program";
  }

  _co2Content(dev) {
    const c = dev.co2 || { enabled: false, before_on: 60, before_off: 60 };
    const options = ['<option value="">— none (off) —</option>'].concat(
      (this._switches || []).map((s) =>
        `<option value="${esc(s.entity_id)}" ${s.entity_id === c.switch ? "selected" : ""}>${esc(s.name)}</option>`)
    ).join("");
    return `
      <label class="field" style="min-width:100%"><span>CO₂ switch</span>
        <select id="co2-switch">${options}</select></label>
      <div class="co2row">
        <label class="field"><span>On before lights</span>
          <input type="number" id="co2-on" min="0" max="360" value="${c.before_on}"></label>
        <label class="field"><span>Off before lights out</span>
          <input type="number" id="co2-off" min="0" max="360" value="${c.before_off}"></label>
      </div>
      ${c.enabled ? `<div class="co2status">
        <span class="led" style="background:${c.on ? "var(--success-color,#16a34a)" : "var(--secondary-text-color)"}"></span>
        <span>${c.on_at ? `CO₂ runs <b class="mono">${c.on_at}–${c.off_at}</b> · currently <b>${c.on ? "ON" : "OFF"}</b>` : "No photoperiod in the current program"}</span>
      </div>` : ""}
      <p class="muted" style="font-size:12px;margin:10px 0 0;line-height:1.5">Follows the active program's photoperiod automatically; off during Blackout, Moonlight, and when the lamps are off / Emergency off.</p>`;
  }

  _tankValue() {
    const tanks = this._tanks ? Object.keys(this._tanks).length : 0;
    const lamps = this._devices.length;
    return `${tanks} tank${tanks === 1 ? "" : "s"} · ${lamps} lamp${lamps === 1 ? "" : "s"}`;
  }

  _tankContent() {
    return `
      <p class="muted" style="margin:0 0 10px;font-size:12px">Give lamps the same tank name to control them together.</p>
      ${this._devices.map((d) => `
        <label class="tankrow">
          <span class="tankname">${esc(d.name)}</span>
          <input type="text" class="tankinput" data-tank="${d.entry_id}" value="${esc(d.tank)}" placeholder="Tank name">
        </label>`).join("")}`;
  }

  async _setCo2(sw, on, off) {
    this._lastInteraction = Date.now();
    this._toast(sw ? "CO₂ linked ✓" : "CO₂ off", "ok");
    try {
      await this._fanout((id) => ({ type: "aqua_chihiros/set_co2", entry_id: id, switch: sw, before_on: on, before_off: off }));
    } catch (err) { this._toast("Could not save CO₂ setting", "error"); }
    await this._load();
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
  :host *, :host *::before, :host *::after { box-sizing:border-box; }
  #topbar:not(:empty) { position:sticky; top:0; z-index:5; display:flex; align-items:center;
    gap:6px; height:52px; padding:0 6px;
    /* Coloured by default in the Chihiros brand teal so the bar reads as part
       of the app, not as HA chrome. A theme can still override it via the
       panel-specific --aqua-chihiros-topbar-* vars (or fall back to the
       app-header vars by setting them to the app-header values). */
    background:var(--aqua-chihiros-topbar-background,
      linear-gradient(135deg, var(--chihiros-accent) 0%, #0c6f74 100%));
    color:var(--aqua-chihiros-topbar-text, #eaf4f6);
    box-shadow:0 2px 4px rgba(0,0,0,.15); }
  .menubtn { border:0; background:transparent; color:inherit; cursor:pointer;
    width:44px; height:44px; border-radius:50%; display:grid; place-items:center; }
  .menubtn:hover { background:rgba(255,255,255,.12); }
  .tbtitle { font-size:18px; font-weight:600; }
  .tblogo { flex:none; }
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
    border-radius:16px; padding:20px; box-shadow:var(--ha-card-box-shadow,none); margin-bottom:14px; }
  .head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px;
    margin:14px 0 18px; }
  .subline { display:flex; align-items:center; gap:7px; margin-top:4px; flex-wrap:wrap;
    font-size:13px; color:var(--secondary-text-color); }

  /* Hero: the live card, framed in accent so it reads as the focal point. */
  .card.hero { border:1.5px solid color-mix(in srgb, var(--chihiros-accent) 45%, var(--divider-color));
    box-shadow:0 0 0 4px color-mix(in srgb, var(--chihiros-accent) 7%, transparent),
      var(--ha-card-box-shadow,none); }
  .herotop { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
  .now { display:flex; align-items:center; gap:9px; min-width:0; }
  .badge { font-size:10px; font-weight:800; letter-spacing:.08em; color:#fff; flex:none;
    background:var(--chihiros-accent); padding:3px 8px; border-radius:999px; }
  .phase { font-weight:600; font-size:14.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .phase small { color:var(--secondary-text-color); font-weight:500; }

  /* Big control rows (Program, Maintenance, Setup). */
  .card.ctlcard { padding:0; overflow:hidden; }
  .ctl, .setrow { display:flex; align-items:center; gap:14px; padding:18px 20px;
    cursor:pointer; user-select:none; }
  .ctl:hover, .setrow:hover { background:color-mix(in srgb, var(--primary-text-color) 3%, transparent); }
  .ctl .ic, .setrow .ic { font-size:22px; flex:none; line-height:1; }
  .ctxt { flex:1; min-width:0; display:flex; flex-direction:column; gap:2px; }
  .ctxt small { font-size:10.5px; letter-spacing:.09em; text-transform:uppercase;
    color:var(--secondary-text-color); font-weight:700; }
  .ctxt b { font-size:17px; font-weight:600; }
  .go { flex:none; font-size:13.5px; font-weight:600; color:var(--chihiros-accent); }
  .ctl.maint .go { color:var(--chihiros-accent); }
  .chev { flex:none; color:var(--secondary-text-color); font-size:14px; }
  .progopts { padding:0 20px 18px; }
  .setbody { border-top:1px solid var(--divider-color); }
  .setrow.sub { padding:14px 20px; border-top:1px solid var(--divider-color); }
  .setrow.sub:first-child { border-top:0; }
  .setrow.sub .ic { font-size:18px; }
  .setrow.sub .ctxt b { font-size:15px; }
  .setrow.sub .ctxt small { text-transform:none; letter-spacing:0; font-weight:500; font-size:12px; }
  .subbody { padding:2px 20px 18px; display:flex; flex-direction:column; gap:14px; }

  /* Devices card: compact, quiet. */
  .card.devices { padding:14px 20px; }
  .util { display:flex; gap:18px; margin-top:6px; padding-top:12px;
    border-top:1px solid var(--divider-color); }
  .util button { border:0; background:transparent; cursor:pointer; font:inherit;
    font-size:12.5px; font-weight:600; color:var(--secondary-text-color); padding:4px 0; }
  .util button:hover { color:var(--primary-text-color); }
  .util button.off:hover { color:var(--error-color,#d8434f); }
  .curvehead { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:12px; }
  .ct { font-weight:600; font-size:14px; }
  canvas { width:100%; display:block; cursor:crosshair; }
  .curvewrap { position:relative; }
  .hovertip { position:absolute; top:-2px; transform:translateX(-50%);
    background:var(--primary-text-color); color:var(--card-background-color);
    font-family:monospace; font-size:12px; font-weight:700; padding:3px 7px;
    border-radius:7px; pointer-events:none; white-space:nowrap; z-index:2;
    box-shadow:0 2px 8px rgba(0,0,0,.25); }
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
  .co2row { display:flex; gap:16px; flex-wrap:wrap; margin-top:14px; }
  select { font:inherit; font-size:14px; padding:10px 12px; border-radius:10px;
    border:1px solid var(--divider-color); background:var(--secondary-background-color);
    color:var(--primary-text-color); width:100%; }
  .co2status { display:flex; align-items:center; gap:9px; margin-top:14px; padding:11px 13px;
    border-radius:11px; background:var(--secondary-background-color); font-size:13px; }
  .co2status .led { width:9px; height:9px; border-radius:50%; flex:none; }
  .treatstart { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:14px;
    padding-top:14px; border-top:1px solid var(--divider-color); font-size:13px; }
  .treatstart input { width:56px; font:inherit; padding:6px 8px; border-radius:8px;
    border:1px solid var(--divider-color); background:var(--secondary-background-color);
    color:var(--primary-text-color); }
  .btn.small { flex:none; padding:8px 14px; font-size:13px; }
  .card.treatment { border-color:color-mix(in srgb, var(--warning-color,#d9971f) 55%, var(--divider-color));
    background:color-mix(in srgb, var(--warning-color,#d9971f) 10%, var(--card-background-color)); }
  .trow { display:flex; align-items:center; gap:12px; }
  .tmark { font-size:22px; flex:none; }
  .tinfo { flex:1; display:flex; flex-direction:column; }
  .tinfo b { font-size:14px; }
  .tbar { height:6px; border-radius:6px; background:var(--secondary-background-color); margin-top:12px; overflow:hidden; }
  .tbar span { display:block; height:100%; background:var(--warning-color,#d9971f); border-radius:6px; }
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
  /* First-time setup wizard */
  .wcard { padding:24px; margin:26px auto 0; max-width:460px; }
  .wsteps { display:flex; gap:7px; margin-bottom:20px; }
  .wsteps i { height:5px; border-radius:99px; background:var(--divider-color); flex:1; transition:.25s; }
  .wsteps i.on { background:var(--chihiros-accent); }
  .wsteps i.done { background:color-mix(in srgb, var(--chihiros-accent) 55%, var(--divider-color)); }
  .weyebrow { font-size:11px; letter-spacing:.16em; text-transform:uppercase;
    color:var(--chihiros-accent); font-weight:800; margin-bottom:6px; }
  .wh { font-size:22px; font-weight:700; margin:0 0 6px; line-height:1.2; }
  .wlead { color:var(--secondary-text-color); font-size:14px; line-height:1.55; margin:0 0 22px; }
  .wpaths { display:flex; flex-direction:column; gap:12px; }
  .wpath { display:flex; gap:14px; align-items:flex-start; text-align:left; width:100%;
    border:1.5px solid var(--divider-color); background:var(--secondary-background-color);
    border-radius:14px; padding:16px; cursor:pointer; font:inherit; color:inherit; transition:.15s; }
  .wpath:hover { border-color:color-mix(in srgb, var(--chihiros-accent) 55%, var(--divider-color)); }
  .wpath .wic { font-size:26px; flex:none; line-height:1; margin-top:1px; }
  .wpath .wtt { flex:1; min-width:0; }
  .wpath .wtt b { display:block; font-size:16px; font-weight:700; }
  .wpath .wtt small { display:block; color:var(--secondary-text-color); font-size:12.5px; margin-top:3px; line-height:1.5; }
  .wpath .wgo { flex:none; color:var(--chihiros-accent); font-size:20px; align-self:center; }
  .wf { display:block; margin-bottom:18px; }
  .wf > span { display:block; font-size:12.5px; font-weight:600; color:var(--secondary-text-color); margin-bottom:8px; }
  .wf input[type=text], .wf select { font:inherit; font-size:15px; padding:12px 13px; border-radius:11px;
    border:1px solid var(--divider-color); background:var(--secondary-background-color);
    color:var(--primary-text-color); width:100%; }
  .wnav { display:flex; align-items:center; gap:12px; margin-top:26px; }
  .wback { border:0; background:transparent; color:var(--secondary-text-color); font:inherit;
    font-weight:600; font-size:14px; cursor:pointer; padding:6px; }
  .wsp { flex:1; }
  .wbtn { border:0; border-radius:12px; padding:13px 22px; font:inherit; font-weight:700; font-size:15px;
    cursor:pointer; background:var(--chihiros-accent); color:#fff; }
  .wbtn:active { transform:translateY(1px); }
  .wrev { border:1px solid var(--divider-color); border-radius:12px; overflow:hidden; }
  .wr { display:flex; justify-content:space-between; gap:12px; padding:13px 15px; font-size:14px; }
  .wr + .wr { border-top:1px solid var(--divider-color); }
  .wr span { color:var(--secondary-text-color); }
  .wr b { font-weight:600; text-align:right; }
  .wdisclaimer { margin:22px 0 0; font-size:11.5px; line-height:1.5; color:var(--ink-3,var(--secondary-text-color)); }
  .wcenter { text-align:center; padding:8px 0; }
  .wdone { width:64px; height:64px; border-radius:50%; display:grid; place-items:center;
    margin:4px auto 18px; background:color-mix(in srgb, var(--success-color,#16a34a) 15%, transparent);
    color:var(--success-color,#16a34a); font-size:32px; }
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
