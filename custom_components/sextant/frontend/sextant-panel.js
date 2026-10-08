/**
 * Sextant panel: a native Home Assistant custom panel (no iframe).
 *
 * One websocket subscription (sextant/subscribe) feeds every mode; the
 * request/response commands in ws.py do the rest. Modes:
 *   live         the floor plan with things, trails and a history scrubber
 *   edit         the floor-plan editor
 *   things     what Bermuda tracks, and what it hears but does not
 *   bermuda      Bermuda's own things: global options, FindMy, Tiles
 *   proxies      proxy health, grouped by floor and room, plus the self-test
 *   calibration  proxy calibration runs
 *   tuning       stability KPI, live tuning, history retention
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { signalColour, SextantMap, thingColor, thingHue, staleness, shortAge, heatCells, pointInPolygon } from "./sextant-map.js";
import { sharedStyles, widgetStyles, fmtAge, fmtNum, toast, confirmDialog, ensureHaComponents, uiSelect, uiButton, callWS, sortFloors, thingName, proxyName, fmtLen, fmtSpeed, classIcon, pronounsFor, uiIconButton, uiSegmented } from "./sextant-ui.js";

// What this page is running: the version of the files it was loaded from
// (sextant-version.js), not the one in its URL - see that file.
import { VERSION as PANEL_VERSION } from "./sextant-version.js";
import "./sextant-devices.js";
import "./sextant-health.js";
import "./sextant-edit.js";

// No advised spots: one array for every render, so the editor does not see a
// new value (and repaint) each time the clock ticks.
const NO_SPOTS = Object.freeze([]);

// A failed layout fetch or subscription is not retried from updated() sooner
// than this: hass changes several times a second. Retry still goes at once.
const RETRY_MS = 30000;

const MODES = [
  ["live", "Live", "mdi:map-marker-radius"],
  ["edit", "Edit", "mdi:vector-polygon"],
  ["things", "Things", "mdi:tag-multiple"],
  ["bermuda", "Bermuda", "mdi:bluetooth-settings"],
  ["proxies", "Proxies", "mdi:access-point-network"],
  ["calibration", "Calibration", "mdi:tune-vertical"],
  ["tuning", "Tuning", "mdi:chart-timeline-variant"],
  ["advice", "Advice", "mdi:lightbulb-on-outline"],
];
const FLOOR_MODES = new Set(["live", "edit", "proxies", "calibration"]);
// Pages that change the layout, the things or Bermuda, or expose every
// address the house hears: administrators only (the backend refuses the
// commands too; this just keeps the tabs out of a non-admin's way).
const ADMIN_MODES = new Set(["edit", "things", "bermuda", "calibration", "tuning"]);
// Modes from before the page split (3.7.0) still stored in the browser.
const MODE_ALIASES = { devices: "things", health: "proxies", trackers: "things" };
const REPO_URL = "https://github.com/davidcoulson/sextant";

export function mapUrlFor(floorName, maps) {
  if (!floorName || !maps) return null;
  const norm = (s) => String(s).toLowerCase().replace(/\.[a-z0-9]+$/, "").replace(/[\s_-]+/g, "");
  const want = norm(floorName);
  const hit = maps.find((m) => norm(m) === want) || maps.find((m) => norm(m).startsWith(want));
  return hit ? `/api/sextant/map/${encodeURIComponent(hit)}` : null;
}

/** Seconds as "40 min" / "2.5 h". */
function shortSpan(secs) {
  if (!(secs > 0)) return "0 min";
  if (secs < 3600) return `${Math.max(1, Math.round(secs / 60))} min`;
  return `${(secs / 3600).toFixed(secs < 36000 ? 1 : 0)} h`;
}

// Battery badge thresholds (percent): amber at LOW, red at CRITICAL.
const BATTERY_LOW = 20;
const BATTERY_CRITICAL = 10;

class SextantPanel extends LitElement {
  static properties = {
    _spots: { state: true },
    hass: { attribute: false },
    narrow: { type: Boolean },
    panel: { attribute: false },
    route: { attribute: false },
    _mode: { state: true },
    _data: { state: true },
    _positions: { state: true },
    _now: { state: true },        // ticks every second, for the countdown
    _intervalMenu: { state: true }, // the countdown's refresh menu is open
    _floor: { state: true },
    _error: { state: true },
  };

  constructor() {
    super();
    this._mode = (() => { try { const m = localStorage.getItem("sextant.mode") || "live"; return MODE_ALIASES[m] || m; } catch { return "live"; } })();
    if (!MODES.some(([id]) => id === this._mode)) this._mode = "live";
    this._data = null;
    this._positions = { positions: [], offline_receivers: [], stamp: 0 };
    this._now = Date.now() / 1000;
    this._cycleSecs = null;       // measured from the gap between cycles
    this._floor = null;
    this._unsub = null;
    this._error = null;
  }

  connectedCallback() {
    super.connectedCallback();
    // HA's form elements are loaded by HA itself; make sure they exist before
    // the first render so the modes pick them instead of the plain fallbacks.
    ensureHaComponents().then(() => this.requestUpdate());
    this._load();
    this._subscribe();
    this._clock = setInterval(() => { this._now = Date.now() / 1000; }, 1000);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._clock);
    if (this._unsub) { this._unsub.then((u) => u()).catch(() => {}); this._unsub = null; }
  }

  updated(changed) {
    const now = Date.now();
    if (changed.has("hass") && this.hass && !this._data && !this._loading && !(now - (this._loadFailedAt || 0) < RETRY_MS)) this._load();
    if (changed.has("hass") && this.hass && !this._unsub && !(now - (this._subFailedAt || 0) < RETRY_MS)) this._subscribe();
  }

  async _load() {
    if (!this.hass) return;
    this._loading = true;
    try {
      const data = await this.hass.callWS({ type: "sextant/layout/get" });
      this._data = data;
      const floors = data.layout?.floor || [];
      if (!this._floor || !floors.some((f) => f.name === this._floor)) this._floor = floors[0]?.name || null;
      this._error = null;
      this._loadFailedAt = 0;
    } catch (e) {
      this._error = e?.message || String(e);
      this._loadFailedAt = Date.now();
    } finally {
      this._loading = false;
    }
  }

  _subscribe() {
    if (!this.hass?.connection || this._unsub) return;
    this._unsub = this.hass.connection.subscribeMessage(
      (payload) => {
        // The gap between cycles is what the countdown counts down from:
        // Bermuda's interval is not ours to read, so it is measured here.
        const gap = payload?.stamp - this._positions?.stamp;
        if (gap > 1 && gap < 300) this._cycleSecs = this._cycleSecs ? this._cycleSecs * 0.5 + gap * 0.5 : gap;
        this._positions = payload;
        this._now = Date.now() / 1000;
      },
      { type: "sextant/subscribe" },
    );
    this._unsub.then(() => { this._subFailedAt = 0; }, (e) => { this._unsub = null; this._subFailedAt = Date.now(); this._error = `live updates: ${e?.message || e}`; });
  }

  _isAdmin() { return this.hass?.user?.is_admin !== false; }

  _modes() { return this._isAdmin() ? MODES : MODES.filter(([id]) => !ADMIN_MODES.has(id)); }

  /** Switch pages. `target` is a mode id, or {mode, thing} to open that
   * thing's dialog once the destination page has loaded - which is how the
   * Live card's edit button reaches the thing settings without a second
   * copy of the dialog living here. */
  /** The editor holds an unsaved draft in the page: ask before anything that
   * would replace it (another floor, another page). True to go ahead. */
  _mayLeaveEdit(what) {
    const editor = this.renderRoot?.querySelector("sextant-edit");
    return !editor?.unsaved || editor.confirmLeave(what);
  }

  _setMode(target) {
    const { mode: wanted, thing } = typeof target === "string" ? { mode: target } : (target || {});
    const mode = this._modes().some(([id]) => id === wanted) ? wanted : "live";
    if (this._mode === "edit" && mode !== "edit" && !this._mayLeaveEdit(`Leave the floor plan`)) return;
    this._mode = mode;
    this._openThing = mode === "things" ? thing || null : null;
    if (mode !== "edit") this._spots = NO_SPOTS;
    try { localStorage.setItem("sextant.mode", mode); } catch { /* private mode */ }
  }

  _onLayoutChanged() { this._load(); }

  render() {
    const floors = this._data?.layout?.floor || [];
    return html`
      <div class="topbar">
        <ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>
        <a class="brand" href="#" title="Back to the live map" @click=${(e) => { e.preventDefault(); this._setMode("live"); }}>
          <ha-icon icon="mdi:compass-rose"></ha-icon>
          <span class="brand-text"><span class="brand-name">Sextant</span><span class="brand-sub">Powered by Bermuda</span></span>
        </a>
        <nav class="modes" role="tablist">
          ${this._modes().map(([id, label, icon]) => html`
            <button role="tab" class=${this._mode === id ? "active" : ""} aria-selected=${this._mode === id}
                    @click=${() => this._setMode(id)} title=${label}>
              <ha-icon icon=${icon}></ha-icon><span class="mode-label">${label}</span>
            </button>`)}
        </nav>
        <div class="spacer"></div>
        <div class="wide-only floorstamp">${this._renderFloorAndStamp(floors)}</div>
        <a class="repo" href=${REPO_URL} target="_blank" rel="noopener" title="Sextant on GitHub"><ha-icon icon="mdi:github"></ha-icon></a>
      </div>
      ${this._error ? html`<div class="banner error">${this._error} <button @click=${() => this._load()}>Retry</button></div>` : nothing}
      ${this._renderVersionBanner()}
      <div class="body">${this._renderMode()}</div>
      <div class="bottombar narrow-only">${this._renderFloorAndStamp(floors)}</div>
    `;
  }

  /**
   * After an update HACS has swapped the files on disk. The frontend is
   * served from disk, so a reload is all a page needs; Home Assistant only
   * has to restart when the Python code changed too (restart_needed compares
   * the code on disk with what was loaded).
   */
  _renderVersionBanner() {
    const installed = this._data?.app_version;
    if (this._data?.restart_needed) {
      return html`<div class="banner update">Sextant ${installed || ""} is installed, and its backend changed. Restart Home Assistant to finish the update.
        ${this.hass?.user?.is_admin ? html`<button @click=${() => this._restartHa()}>Restart</button>` : nothing}</div>`;
    }
    if (installed && PANEL_VERSION && installed !== PANEL_VERSION) {
      return html`<div class="banner update">Sextant ${installed} is installed; this page is still ${PANEL_VERSION}. <button @click=${() => window.location.reload()}>Reload</button></div>`;
    }
    return nothing;
  }

  async _restartHa() {
    if (!confirmDialog("Restart Home Assistant now? Everything is unavailable for a minute or two.")) return;
    await this.hass.callService("homeassistant", "restart");
  }

  /** The floor picker (when the mode has floors) and the cycle-age stamp.
   * On a wide screen these sit in the topbar; on a phone the topbar has no
   * room to spare for them without pushing the mode tabs into a sideways
   * scroll, so they move to a slim bar under the page instead (CSS picks
   * which copy renders - see .wide-only/.narrow-only). */
  _renderFloorAndStamp(floors) {
    return html`
      ${floors.length && FLOOR_MODES.has(this._mode) ? html`
        <div class="floor-tabs" role="tablist" aria-label="Floor">
          ${sortFloors(floors, true).map((f) => {
            const on = f.name === this._floor;
            const n = this._mode === "live" ? this._thingsOn(f.name) : null;
            return html`<button role="tab" class=${on ? "active" : ""} aria-selected=${on}
              title=${n === null ? f.name : `${f.name}: ${n} thing${n === 1 ? "" : "s"} here now`}
              @click=${() => this._pickFloor(f.name)}>${f.name}${n ? html`<span class="n">${n}</span>` : nothing}</button>`;
          })}
        </div>` : nothing}
      ${this._renderStamp()}
    `;
  }

  /** One click to another floor. It goes through the same unsaved-draft guard
   * the dropdown did: in Edit a floor switch is an unsaved plan being left. */
  _pickFloor(name) {
    if (name === this._floor) return;
    if (!this._mayLeaveEdit(`Switch to ${name}`)) return;
    this._floor = name;
  }

  /** How many things are on a floor right now, for the Live tabs: where
   * everyone is, without switching to look. */
  _thingsOn(floorName) {
    const rows = this._positions?.positions || [];
    return rows.filter((r) => r.floor === floorName).length;
  }

  /** Seconds until the next positioning cycle; the age of the last one while
   * a cycle is overdue (a proxy went quiet, the house is asleep). The backend
   * says what the interval is; an older one did not, and then the gap between
   * cycles is measured instead. For an admin the countdown is also a menu that
   * sets a faster (or slower) refresh for a quarter of an hour. */
  _renderStamp() {
    const info = this._positions?.interval;
    const at = info?.last_cycle_at ?? this._positions.stamp;
    const age = at ? this._now - at : null;
    const every = info?.secs ?? this._cycleSecs;
    const left = every && age != null ? Math.ceil(every - age) : null;
    const counting = left != null && left >= 0;
    const override = !!info?.until;
    const content = html`<ha-icon icon=${counting ? "mdi:timer-sand" : "mdi:update"}></ha-icon>${age == null ? "—" : counting ? `${left}s` : fmtAge(age)}`;
    if (!info || !this._isAdmin()) {
      return html`<span class="stamp" title=${counting ? "Seconds until the next positioning cycle" : "Time since the last positioning cycle"}>${content}</span>`;
    }
    const title = override
      ? `Refreshing every ${every} s until ${this._clockTime(info.until)}, then every ${info.configured} s. Click to change`
      : `Refreshing every ${every} s. Click to refresh faster for a while`;
    return html`<span class="stampwrap" @keydown=${(e) => { if (e.key === "Escape") this._intervalMenu = false; }}>
      <button class="stamp stampbtn ${override ? "override" : ""}" aria-haspopup="menu" aria-expanded=${this._intervalMenu ? "true" : "false"}
              title=${title} @click=${() => { this._intervalMenu = !this._intervalMenu; }}>
        ${content}${override ? html`<span class="every">every ${every}s</span>` : nothing}<ha-icon class="caret" icon="mdi:menu-down"></ha-icon>
      </button>
      ${this._intervalMenu ? this._renderIntervalMenu(info) : nothing}
    </span>`;
  }

  _clockTime(epoch) {
    return new Date(epoch * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  _renderIntervalMenu(info) {
    return html`<div class="imenu-backdrop" @click=${() => { this._intervalMenu = false; }}></div>
      <div class="imenu" role="menu" aria-label="Refresh every">
        <div class="imenu-head">Refresh every</div>
        ${info.choices.map((secs) => {
          const on = secs === info.secs;
          const normal = secs === info.configured;
          return html`<button role="menuitemradio" aria-checked=${on ? "true" : "false"} class=${on ? "on" : ""}
                              @click=${() => this._setInterval(normal ? null : secs)}>
            <span class="tick">${on ? html`<ha-icon icon="mdi:check"></ha-icon>` : nothing}</span>
            <span>${secs} s</span>${normal ? html`<span class="dim">normal</span>` : nothing}
          </button>`;
        })}
        <div class="imenu-foot">
          ${info.until ? `Back to ${info.configured} s at ${this._clockTime(info.until)}.` : `Anything but normal lasts 15 minutes.`}
          ${info.last_cycle_ms != null ? html`<br>The last cycle took ${info.last_cycle_ms} ms.` : nothing}
        </div>
      </div>`;
  }

  async _setInterval(secs) {
    this._intervalMenu = false;
    const info = await callWS(this, this.hass, { type: "sextant/interval/set", secs });
    if (info) {
      this._positions = { ...this._positions, interval: info };
      toast(this, secs == null ? `Back to every ${info.configured} s` : `Refreshing every ${secs} s until ${this._clockTime(info.until)}`);
    }
  }

  _renderMode() {
    if (!this._data && !this._error) return html`<div class="empty">Loading…</div>`;
    switch (this._mode) {
      case "edit":
        return html`<sextant-edit .hass=${this.hass} .data=${this._data} .floor=${this._floor} .narrow=${this.narrow} .spots=${this._spots || NO_SPOTS}
                                  @layout-changed=${() => this._onLayoutChanged()} @floor-changed=${(e) => { this._floor = e.detail; }}></sextant-edit>`;
      case "things":
      case "bermuda":
        return html`<sextant-devices .hass=${this.hass} .data=${this._data} .positions=${this._positions} .section=${this._mode}
                                     .openThing=${this._openThing}
                                     @layout-changed=${() => this._onLayoutChanged()}
                                     @thing-opened=${() => { this._openThing = null; }}
                                     @quick-nav=${(e) => this._setMode(e.detail)}></sextant-devices>`;
      case "proxies":
      case "calibration":
      case "tuning":
      case "advice":
        return html`<sextant-health .hass=${this.hass} .data=${this._data} .positions=${this._positions} .floor=${this._floor} .section=${this._mode}
                                    @layout-changed=${() => this._onLayoutChanged()}
                                    @show-spots=${(e) => { this._spots = e.detail.spots; this._floor = e.detail.floor; this._setMode("edit"); this._spots = e.detail.spots; }}></sextant-health>`;
      default:
        return html`<sextant-live .hass=${this.hass} .data=${this._data} .positions=${this._positions} .floor=${this._floor}
                                  @layout-changed=${() => this._onLayoutChanged()} @floor-changed=${(e) => { this._floor = e.detail; }}
                                  @quick-nav=${(e) => this._setMode(e.detail)}></sextant-live>`;
    }
  }

  static styles = [sharedStyles, css`
    :host { display: flex; flex-direction: column; height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color); }
    .topbar { display: flex; align-items: center; gap: 10px; padding: 0 12px; height: 56px; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); flex: none; }
    .brand { display: flex; align-items: center; gap: 8px; margin-right: 8px; color: inherit; text-decoration: none; }
    .brand ha-icon { --mdc-icon-size: 26px; }
    .brand-text { display: flex; flex-direction: column; line-height: 1.05; }
    .brand-name { font-weight: 600; font-size: 18px; }
    .brand-sub { font-size: 9px; letter-spacing: 0.04em; opacity: 0.75; text-transform: uppercase; }
    .modes { display: flex; gap: 2px; }
    .modes button { display: flex; align-items: center; gap: 6px; background: transparent; color: inherit; border: 0; border-bottom: 3px solid transparent; padding: 0 10px; height: 56px; cursor: pointer; font: inherit; opacity: 0.8; }
    .modes button.active { opacity: 1; border-bottom-color: currentColor; }
    .modes button:hover { opacity: 1; }
    .spacer { flex: 1; }
    /* Floors as one-click tabs rather than a dropdown: every floor is on
       screen, and switching is one click instead of two. A segmented control,
       so it reads as "which floor" and not as another page like the modes. */
    .floorstamp { display: flex; align-items: center; gap: 10px; }
    /* The tabs sit in the header, whose colours are the theme's: a dark bar
     * with light text, or in a light theme a white bar with dark text. Every
     * colour here is a tint of the header's TEXT colour, and the picked tab
     * is that colour inverted - so it is a white pill on a dark header and a
     * dark pill on a white one. Hard-coded white pills vanished on a white
     * header, taking the floor you were on with them. */
    .floor-tabs { --ink: var(--app-header-text-color, var(--primary-text-color, #212121)); --paper: var(--app-header-background-color, var(--card-background-color, #fff));
      display: flex; gap: 2px; padding: 3px; border-radius: 9px; background: color-mix(in srgb, var(--ink) 12%, transparent); flex: none; }
    .floor-tabs button { display: flex; align-items: center; gap: 6px; background: transparent; border: 0; color: inherit; font: inherit; font-size: 13px; padding: 5px 12px; border-radius: 7px; cursor: pointer; opacity: 0.85; white-space: nowrap; }
    .floor-tabs button:hover { opacity: 1; background: color-mix(in srgb, var(--ink) 10%, transparent); }
    .floor-tabs button.active { opacity: 1; font-weight: 600; background: var(--ink); color: var(--paper); }
    .floor-tabs button:focus-visible { outline: 2px solid currentColor; outline-offset: 1px; }
    .floor-tabs .n { font-size: 11px; font-weight: 600; min-width: 16px; padding: 0 4px; border-radius: 8px; background: color-mix(in srgb, var(--ink) 18%, transparent); text-align: center; }
    .floor-tabs button.active .n { background: color-mix(in srgb, var(--paper) 28%, transparent); color: inherit; }
    .bottombar .floor-tabs { background: var(--secondary-background-color, rgba(0,0,0,0.05)); }
    .bottombar .floor-tabs button:hover { background: rgba(0,0,0,0.05); }
    .bottombar .floor-tabs button.active { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
    .bottombar .floor-tabs .n { background: rgba(0,0,0,0.08); }
    .bottombar .floor-tabs button.active .n { background: rgba(255,255,255,0.25); color: inherit; }
    .stamp { display: inline-flex; align-items: center; gap: 3px; font-variant-numeric: tabular-nums; opacity: 0.8; font-size: 12px; min-width: 40px; justify-content: flex-end; }
    .stamp ha-icon { --mdc-icon-size: 16px; }
    /* The countdown as a menu button (admins): it keeps the stamp's look, and
       says so when a temporary interval is on. */
    .stampwrap { position: relative; display: inline-flex; }
    .stampbtn { background: transparent; border: 0; color: inherit; font: inherit; font-size: 12px; cursor: pointer; padding: 4px 4px 4px 6px; border-radius: 6px; }
    .stampbtn:hover, .stampbtn[aria-expanded="true"] { opacity: 1; background: color-mix(in srgb, currentColor 12%, transparent); }
    .stampbtn:focus-visible { outline: 2px solid currentColor; outline-offset: 1px; }
    .stampbtn.override { opacity: 1; font-weight: 600; }
    .stampbtn .every { font-weight: 400; opacity: 0.8; margin-left: 4px; }
    .stampbtn .caret { --mdc-icon-size: 16px; margin-left: -1px; opacity: 0.8; }
    .imenu-backdrop { position: fixed; inset: 0; z-index: 9; }
    .imenu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 10; min-width: 190px; padding: 6px 0; border-radius: 10px;
      background: var(--card-background-color, #fff); color: var(--primary-text-color); box-shadow: 0 6px 24px rgba(0,0,0,0.28); font-size: 14px; font-weight: 400; }
    .bottombar .imenu { top: auto; bottom: calc(100% + 6px); }
    .imenu-head { padding: 6px 14px 4px; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
    .imenu button { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 14px; background: transparent; border: 0; color: inherit; font: inherit; text-align: left; cursor: pointer; font-variant-numeric: tabular-nums; }
    .imenu button:hover, .imenu button:focus-visible { background: var(--secondary-background-color, rgba(0,0,0,0.06)); outline: none; }
    .imenu button.on { font-weight: 600; }
    .imenu .tick { width: 18px; display: inline-flex; color: var(--primary-color); }
    .imenu .tick ha-icon { --mdc-icon-size: 18px; }
    .imenu .dim { margin-left: auto; font-size: 12px; font-weight: 400; color: var(--secondary-text-color); }
    .imenu-foot { padding: 8px 14px 4px; margin-top: 4px; border-top: 1px solid var(--divider-color); font-size: 12px; line-height: 1.45; color: var(--secondary-text-color); }
    ha-menu-button { --mdc-icon-button-size: 40px; }
    .repo { color: inherit; opacity: 0.85; display: flex; align-items: center; }
    .repo:hover { opacity: 1; }
    .body { flex: 1; min-height: 0; display: flex; }
    .body > * { flex: 1; min-width: 0; }
    .banner.error { background: var(--error-color, #b00020); color: #fff; padding: 8px 12px; }
    .banner.update { background: var(--warning-color, #c77800); color: #fff; padding: 8px 12px; }
    .banner button { margin-left: 8px; }
    .sr { position: absolute; left: -9999px; }
    .narrow-only { display: none; }
    .bottombar { align-items: center; justify-content: flex-end; gap: 10px; padding: 6px 10px; background: var(--card-background-color); border-top: 1px solid var(--divider-color); flex: none; padding-bottom: max(6px, env(safe-area-inset-bottom)); }
    .bottombar .stamp { color: var(--secondary-text-color); }
    @media (max-width: 960px) { .mode-label { display: none; } .modes button { padding: 0 8px; } }
    /* Below 720px the topbar has only the brand mark, the mode tabs and the
       menu button - the floor picker and the cycle-age stamp move to the
       bottombar instead of eating the width the tabs need, which is what
       forced the tab strip into a sideways scroll. */
    @media (max-width: 720px) {
      .brand-text { display: none; }
      .topbar { gap: 4px; padding: 0 6px; }
      .brand { margin-right: 2px; }
      .repo { display: none; }
      .wide-only { display: none; }
      .narrow-only { display: flex; }
      .modes button { padding: 0 8px; }
      /* Freeing the floor picker and stamp usually leaves enough room for
         all 8 tabs; this is only a safety net on a very narrow phone. */
      .modes { overflow-x: auto; scrollbar-width: none; }
    }
  `];
}

// --- Live mode ------------------------------------------------------------------

class SextantLive extends LitElement {
  static properties = {
    hass: { attribute: false },
    data: { attribute: false },
    positions: { attribute: false },
    floor: { type: String },
    _selected: { state: true },
    _options: { state: true },
    _history: { state: true },
    _scrub: { state: true },
    _links: { state: true },
    _marking: { state: true },
    _proxy: { state: true },       // the proxy card, opened by clicking one on the map
    _heat: { state: true },
    _folded: { state: true },
    _truth: { state: true },
    _marks: { state: true },
    _blend: { state: true },
    _optionsOpen: { state: true },
    _mapOpen: { state: true },
    _timeline: { state: true },
    _timelineAll: { state: true },
    _pin: { state: true },
  };

  constructor() {
    super();
    this._selected = null;
    // The quick-pin wizard (phones): null, or {step, ent, result}. "who" lists
    // the things to pin, "where" is the full-screen map with the ring, "done"
    // the pin's evaluation. See _startPin.
    this._pin = null;
    this._links = null;
    this._marking = false;  // waiting for the click that says where the thing really is
    this._heatHours = 0;    // Activity window picked for the selected thing (0 = off)
    try { this._folded = new Set(JSON.parse(localStorage.getItem("sextant.live.folded") || "[]")); } catch { this._folded = new Set(); }
    this._heat = null;      // {ent, hours, byFloor} from heatCells
    this._truth = null;     // the last mark's evaluation {mark, rows, current_weight}
    this._marks = [];       // the selected thing's marks
    this._blend = null;     // slider value while it is being dragged (0..100)
    this._options = { circles: false, fingerprint: false, trails: true, grid: "off", labels: true, subzones: true, receivers: true, access_points: true, image: true };
    try { Object.assign(this._options, JSON.parse(localStorage.getItem("sextant.live.options") || "{}")); } catch { /* ignore */ }
    this._history = null; // {ent, from, to, points:[{t,x,y,f}] }
    this._timeline = null; // {ent, at, stays:[{start,end,floor,room,spot,unheard?,partial?}], last_heard}
    this._timelineAll = false;
    this._scrub = null;   // seconds, absolute
    this._icons = new Map();
    this._optionsOpen = false; // the map-options sheet, phone-width only
    // On a phone the map starts collapsed below the thing list - "where is
    // everything" reads faster as text than as a floor plan on a small
    // screen. Selecting a thing opens it (that's when the spatial view
    // earns its space); the list header also offers it as a plain toggle,
    // for a look at the whole floor without focusing any one thing.
    // Meaningless above 720px, where the map and the list sit side by side.
    this._mapOpen = false;
  }

  /** Whether this hass user may reach an admin-only page - mirrors the
   * panel's own check, used here only to decide which quick-action
   * shortcuts to offer (the destination page enforces the real gate). */
  _isAdmin() { return this.hass?.user?.is_admin !== false; }

  /** Ask the panel to switch pages, for a quick-action shortcut. */
  _goto(mode) { this.dispatchEvent(new CustomEvent("quick-nav", { detail: mode, bubbles: true, composed: true })); }

  firstUpdated() {
    this._restoreDetailHeight();
    // The room for the card changes with the screen and with the map: a
    // height saved on a tall phone is cut to fit a short one.
    if (typeof ResizeObserver !== "undefined") { this._hostResize = new ResizeObserver(() => this._restoreDetailHeight()); this._hostResize.observe(this); }
    this._map = new SextantMap(this.renderRoot.querySelector("canvas"), {
      fetch: (url) => this.hass.fetchWithAuth(url),
      onSelect: (hit) => {
        if (hit?.kind === "receiver") return this._openProxy(hit.index);
        if (hit?.kind === "ap") return;   // named on the map; the focused thing and the proxy card stay
        this._proxy = null;
        this._select(hit?.kind === "thing" ? hit.ent : null);
      },
      onMapClick: (m) => this._placeMark(m),
      isPlacing: () => this._marking,
      onView: () => this._pinViewChanged(),
      onFloorReady: () => { if (this._pin?.step === "where") requestAnimationFrame(() => this._pinZoom()); },
    });
    this._linksTimer = setInterval(() => { if (this._selected) this._loadLinks(); }, 10000);
    // The signal map changes slowly: a minute between looks is plenty.
    this._wifiHeatTimer = setInterval(() => { if (this._options.wifi_heat) this._loadWifiHeat(); }, 60000);
    this._pushFloor();
    this._pushThings();
  }

  disconnectedCallback() { super.disconnectedCallback(); this._map?.destroy(); clearInterval(this._linksTimer); clearInterval(this._wifiHeatTimer); this._hostResize?.disconnect(); }

  _select(ent) {
    if (ent !== this._selected) { this._truth = null; this._marking = false; this._blend = null; this._heat = null; }
    this._selected = ent;
    if (ent) {
      this._mapOpen = true; // a phone: the map opens under this thing's details
      // The quick actions open inside the selected row, so keep that row in
      // view - no further: tapping a visible row moves nothing, picking a
      // thing on the map brings its row into the list's view.
      this.updateComplete.then(() => this.renderRoot.querySelector(".list li.selected")?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    }
    this._map?.setOptions({ focus: ent });
    if (ent) { this._loadLinks(); this._loadMarks(ent); this._loadTimeline(ent); if (this._heatHours) this._loadHeat(ent, this._heatHours); } else { this._links = null; this._marks = []; this._map?.setMarks([]); this._timeline = null; }
  }

  /** Seconds unheard before a thing is shown as a ghost (tuning stale_after_secs). */
  _staleAfter() {
    const own = this.data?.layout?.tuning?.stale_after_secs;
    const dflt = this.data?.tuning_spec?.stale_after_secs?.default;
    return typeof own === "number" ? own : typeof dflt === "number" ? dflt : 120;
  }

  async _loadTimeline(ent) {
    if (!this._isAdmin()) return;   // where people have been: administrators only
    try {
      const r = await this.hass.callWS({ type: "sextant/history/timeline", entity: ent, hours: 24 });
      if (this._selected !== ent || !this._isAdmin()) return;   // selection or access changed while in flight
      this._timeline = { ent, at: Date.now(), ...r };
    } catch (_e) {
      // Older backend: the card just leaves the timeline out. Marked failed
      // rather than cleared so the once-a-minute throttle holds off retries.
      if (this._selected === ent) this._timeline = { ent, at: Date.now(), failed: true };
    }
  }

  async _loadMarks(ent) {
    if (!this._isAdmin()) return;
    const r = await this.hass.callWS({ type: "sextant/truth/list", entity: ent }).catch(() => null);
    if (r && ent === this._selected && this._isAdmin()) { this._marks = r.marks || []; this._pushMarks(); }
  }

  /**
   * The things you do to a selected thing, one tap away at the top of its
   * card instead of a scroll down: mark where it really is, where it has
   * been, scrub its history, edit it.
   */
  _renderQuick(sel) {
    const ent = sel.ent, h = this._history, name = this._label(ent), pn = this._pn(ent);
    const heatOn = this._heat?.ent === ent && this._heatHours > 0;
    const btn = (icon, label, title, on, onClick) => html`<button class="qa ${on ? "on" : ""}" title=${title} aria-label=${title} aria-pressed=${on} @click=${onClick}>
      <ha-icon icon=${icon}></ha-icon><span>${label}</span></button>`;
    // On a phone, Here and Dock open the quick-pin wizard at its map step
    // instead of arming a tap on a half-height map further down the page.
    const mark = () => { if (this._narrow()) this._startPin(ent); else this._marking = !this._marking; };
    return html`<div class="quick">
      ${this._robotOf(ent)
        ? btn("mdi:home-import-outline", "Dock", `Tap where ${name}'s dock is`, this._marking, mark)
        : btn("mdi:map-marker-check", "Here", `Tap where ${name} really is`, this._marking, mark)}
      ${btn("mdi:fire", "Activity", `Where ${name} ${pn.has} spent ${pn.poss} time`, heatOn, () => this._loadHeat(ent, heatOn ? 0 : (this._lastHeatHours || 6)))}
      ${this._isAdmin() ? btn("mdi:history", "History", `Scrub ${name}'s history`, h?.ent === ent, () => this._loadHistory(h?.ent === ent ? null : ent)) : nothing}
      ${this._isAdmin() ? btn("mdi:pencil-outline", "Edit", "Edit this thing", false, () => this._goto({ mode: "things", thing: ent })) : nothing}
    </div>
    ${this._marking ? this._renderMarkingPrompt(ent) : nothing}`;
  }

  _renderMarkingPrompt(ent) {
    return html`
<div class="marking">${this._robotOf(ent) ? html`Tap where ${this._label(ent)}'s dock is on the ${this.floor} plan (the robot need not be on it).` : html`Tap where ${this._label(ent)} really is on the ${this.floor} plan.`} Pinch to zoom, or zoom straight to a spot:
          <div class="zoomto">${(this._floorObj()?.subzones || []).filter((s) => (s.cords || []).length >= 3)
            .sort((a, b) => String(a.entity_id).localeCompare(String(b.entity_id)))
            .map((s) => uiButton({ label: s.entity_id, kind: "text", onClick: () => this._map?.zoomTo(s.cords) }))}
            ${uiButton({ label: "Whole floor", kind: "text", onClick: () => this._map?.fit() })}</div>
          ${uiButton({ label: "Cancel", kind: "text", onClick: () => { this._marking = false; } })}</div>`;
  }

  // --- Quick pin (phones) ------------------------------------------------------
  //
  // Placing a location pin on a phone used to mean: find the thing in the
  // list, scroll past the half-height map to its card, tap an unlabelled
  // icon, scroll back up, pinch, and tap with a finger over the very point.
  // The wizard does it in two taps and a drag: pick the thing (the ones in
  // your own room first - you are standing next to the one you mean), then
  // drag the plan under a fixed ring on a full-screen map and press one
  // button. The finger never covers the point. Same backend calls as the
  // desktop flow; this is only a different way to arrive at x, y.

  /** The stacked-layout breakpoint (see the media query in the styles). */
  _narrow() { return typeof window !== "undefined" && !!window.matchMedia?.("(max-width: 720px)").matches; }

  /** Where this user is right now, from their person's Sextant sensors: {room, floor} or null. */
  _myPlace() {
    const uid = this.hass?.user?.id, states = this.hass?.states || {};
    const person = uid ? Object.values(states).find((s) => s.entity_id.startsWith("person.") && s.attributes?.user_id === uid) : null;
    if (!person) return null;
    const slug = person.entity_id.slice(7);
    const loc = states[`sensor.${slug}_sextant_person_location`];
    const room = loc?.attributes?.room, floor = loc?.attributes?.floor;
    if (!room || room === "unknown") return null;
    return { room, floor: floor && floor !== "unknown" ? floor : null };
  }

  /** Open the wizard: at the map with `ent` already chosen, else at the list. */
  _startPin(ent = null) {
    if (!this._isAdmin()) return;
    this._marking = false;
    this._proxy = null;
    if (!ent) { this._pin = { step: "who" }; return; }
    this._select(ent);
    this._pin = { step: "where", ent };
    const p = this._allRows().find((r) => r.ent === ent), me = this._myPlace();
    // The thing's floor when it has one, else yours; zoomed to your room when
    // you are on that floor, else to where Sextant has the thing.
    const floor = p?.floor || me?.floor || this.floor;
    if (floor !== this.floor) this.dispatchEvent(new CustomEvent("floor-changed", { detail: floor, bubbles: true, composed: true }));
    const room = (me?.floor === floor && me.room) || (p?.floor === floor && p?.zone) || null;
    this._pinFocus = room ? { room } : {};
    // The stage has just gone full-screen (and maybe changed floor): let it
    // lay out and the canvas resize before zooming into it.
    this.updateComplete.then(() => requestAnimationFrame(() => requestAnimationFrame(() => this._pinZoom())));
  }

  _endPin() { this._pin = null; this._pinFocus = null; this._pinAt = null; this._pinViewKey = null; }

  // --- The details card's height (phones) ------------------------------------
  //
  // Under 720px the selected thing's card sits under the list and takes
  // what it needs, which on a long timeline is most of the screen. The grip
  // on its top edge drags its height; the choice is kept per browser, and a
  // double tap on the grip goes back to letting the content decide.

  _detailHeightKey = "sextant.live.detailHeight";
  static DETAIL_MIN = 120;   // the card never shrinks below this
  static LIST_MIN = 120;     // ...and always leaves the list at least this

  /** The tallest the card may be here: what is left after the quick actions,
   * the map (when open) and a usable strip of list. */
  _detailMax() {
    const host = this.getBoundingClientRect().height || window.innerHeight;
    const h = (sel) => this.renderRoot.querySelector(sel)?.getBoundingClientRect().height || 0;
    const stage = this._mapOpen ? h(".stage") : 0;
    return Math.max(80, Math.floor(host - h(".quick-actions") - stage - SextantLive.LIST_MIN));
  }

  _clampDetail(px) { return Math.round(Math.min(Math.max(px, SextantLive.DETAIL_MIN), Math.max(this._detailMax(), 80))); }

  /** A height saved on a taller screen is cut to fit this one; re-run whenever the room changes (resize, map open). */
  _restoreDetailHeight() {
    let saved = null;
    try { saved = Number(localStorage.getItem(this._detailHeightKey)) || null; } catch { /* ignore */ }
    if (saved) this.style.setProperty("--sextant-detail-h", `${this._clampDetail(saved)}px`);
  }

  _detailHeight() { const v = parseFloat(this.style.getPropertyValue("--sextant-detail-h")); return Number.isFinite(v) ? v : null; }

  _setDetailHeight(px) {
    if (px == null) { this.style.removeProperty("--sextant-detail-h"); try { localStorage.removeItem(this._detailHeightKey); } catch { /* ignore */ } return; }
    const h = this._clampDetail(px);
    this.style.setProperty("--sextant-detail-h", `${h}px`);
    try { localStorage.setItem(this._detailHeightKey, String(h)); } catch { /* ignore */ }
  }

  /** Arrows resize from the keyboard; Backspace, Delete or Escape go back to the content's own height. */
  _gripKey(e) {
    const step = e.shiftKey ? 80 : 24;
    const card = e.currentTarget.closest(".detail");
    const cur = this._detailHeight() ?? card?.getBoundingClientRect().height ?? SextantLive.DETAIL_MIN;
    if (e.key === "ArrowUp") this._setDetailHeight(cur + step);
    else if (e.key === "ArrowDown") this._setDetailHeight(cur - step);
    else if (e.key === "Backspace" || e.key === "Delete" || e.key === "Escape") this._setDetailHeight(null);
    else return;
    e.preventDefault();
  }

  _gripDown(e) {
    const card = e.currentTarget.closest(".detail");
    if (!card) return;
    this._grip = { y: e.clientY, h: card.getBoundingClientRect().height };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  }

  _gripMove(e) {
    if (!this._grip) return;
    this._setDetailHeight(this._grip.h + (this._grip.y - e.clientY));   // dragging up grows the card
  }

  _gripUp(e) {
    if (!this._grip) return;
    this._grip = null;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* already released */ }
  }

  _pinZoom() {
    if (this._pin?.step !== "where") return;
    const f = this._floorObj(), focus = this._pinFocus || {};
    if (focus.spot) { const s = (f?.subzones || []).find((z) => z.entity_id === focus.spot); if (s?.cords?.length >= 3) return this._map?.zoomTo(s.cords, 0.55); }
    if (focus.room) { const z = (f?.zones || []).find((z) => z.entity_id === focus.room); if (z?.cords?.length >= 3) return this._map?.zoomTo(z.cords, 0.1); }
    this._map?.fit();
  }

  /** The map point under the ring, with the room and spot it falls in. */
  _pinUnderRing() {
    const c = this._map?.canvas;
    if (!c) return null;
    const rect = c.getBoundingClientRect();
    if (!rect.width) return null;
    const m = this._map.toMap({ x: rect.width / 2, y: rect.height / 2 });
    const f = this._floorObj();
    const inside = (list) => (list || []).find((z) => !z.no_go && (z.cords || []).length >= 3 && pointInPolygon(m, z.cords));
    return { m, room: inside(f?.zones)?.entity_id || null, spot: inside(f?.subzones)?.entity_id || null };
  }

  /** The map redrew (a pan, a pinch): refresh the ring's caption without a re-render per frame. */
  _pinViewChanged() {
    if (this._pin?.step !== "where") return;
    // Every position update redraws too; only a moved view or a new floor
    // can change what is under the ring.
    const v = this._map?.view, f = this._floorObj();
    const key = v ? `${f?.name}|${v.k}|${v.tx}|${v.ty}` : null;
    if (key === this._pinViewKey && f === this._pinViewFloor) return;
    this._pinViewKey = key; this._pinViewFloor = f;
    const at = this._pinUnderRing();
    if (!at) return;
    this._pinAt = at;
    const el = this.renderRoot.querySelector(".pinunder");
    if (el) el.textContent = at.spot ? `${at.spot} · ${at.room || this.floor}` : (at.room || `Off the rooms · ${this.floor}`);
  }

  async _pinPlace() {
    const pin = this._pin;
    if (pin?.step !== "where" || !pin.ent) return;
    const at = this._pinUnderRing();
    if (!at) return;
    const ent = pin.ent, vacuum = this._robotOf(ent);
    // The busy state is this operation's identity: Back, another thing or
    // Done while the call is in flight replace it, and the answer then
    // changes the store but not the wizard.
    const busy = { ...pin, busy: true };
    this._pin = busy;
    const mine = () => this._pin === busy;
    if (vacuum) {
      const r = await callWS(this, this.hass, { type: "sextant/robot/dock", vacuum, floor: this.floor, x: at.m.x, y: at.m.y });
      if (!r) { if (mine()) this._pin = pin; return; }
      toast(this, r.fit ? `Dock marked: ${r.fit.pairs.length} points agree to ${fmtNum(r.fit.rms_m, 2)} m` : "Dock marked");
      this.dispatchEvent(new CustomEvent("layout-changed"));
      if (mine()) this._endPin();
      return;
    }
    const r = await callWS(this, this.hass, { type: "sextant/truth/mark", entity: ent, floor: this.floor, x: at.m.x, y: at.m.y });
    if (!r) { if (mine()) this._pin = pin; return; }
    this._loadMarks(ent);
    this.dispatchEvent(new CustomEvent("layout-changed"));
    if (!mine()) return;
    this._truth = r;
    this._pin = { step: "done", ent, result: r, room: at.room, spot: at.spot };
  }

  /** Undo from the done step: forget the pin just placed and go back to the list. */
  async _pinUndo() {
    const pin = this._pin, id = pin?.result?.mark?.id;
    // No "are you sure?": the tap on Undo is the confirmation, and a blocking
    // confirm() under a full-screen sheet is easy to lose on a phone.
    if (id != null) {
      const r = await callWS(this, this.hass, { type: "sextant/truth/delete", mark_id: id });
      if (!r) return;
      if (this._truth?.mark?.id === id) this._truth = null;
      this._loadMarks(this._selected);
      this.dispatchEvent(new CustomEvent("layout-changed"));
      toast(this, `Pin ${id} forgotten`);
    }
    if (this._pin === pin) this._pin = { step: "who" };   // unless the wizard moved on meanwhile
  }

  _renderPinWho() {
    const me = this._myPlace();
    const rows = this._allRows();
    const pick = (ent) => () => this._startPin(ent);
    const near = me ? rows.filter((p) => !this._state(p).ghost && p.zone === me.room && (!me.floor || !p.floor || p.floor === me.floor)) : [];
    const nearSet = new Set(near.map((p) => p.ent));
    const rest = rows.filter((p) => !nearSet.has(p.ent));
    const live = rest.filter((p) => !this._state(p).ghost), quiet = rest.filter((p) => this._state(p).ghost);
    const row = (p, big) => {
      const st = this._state(p), pn = this._pn(p.ent);
      const where = st.away ? "away" : [p.zone, p.sub_zone && p.sub_zone !== "unknown" ? p.sub_zone : null].filter(Boolean).join(" · ") || "somewhere";
      const when = st.away ? "" : st.age ? ` · ${shortAge(st.age)} ago` : "";
      return html`<li><button class="pinrow ${big ? "big" : ""} ${st.ghost ? "ghost" : ""}" @click=${pick(p.ent)}
          title=${st.ghost ? `Not heard for ${fmtAge(st.age)}: the pin would have nothing recent to re-solve` : `Pin where ${this._label(p.ent)} really ${pn.is}`}>
        ${this._avatar(p.ent)}
        <span class="pintext"><span class="name">${this._label(p.ent)}</span><span class="muted small">${st.ghost ? "" : "Sextant: "}${where}${when}</span></span>
        <ha-icon icon="mdi:chevron-right"></ha-icon></button></li>`;
    };
    return html`<div class="pinsheet" role="dialog" aria-label="Quick pin: who">
      <div class="pinhead">
        <button class="iconbtn round" title="Close" aria-label="Close" @click=${() => this._endPin()}><ha-icon icon="mdi:close"></ha-icon></button>
        <div><div class="muted small">Quick pin · 1 of 2</div><h3>${me ? "Who's with you?" : "Who?"}</h3></div>
      </div>
      <div class="pinbody">
        ${me ? html`<div class="pinsection accent">In the ${me.room} with you</div>
          <ul class="plain">${near.length ? near.map((p) => row(p, true)) : html`<li class="muted small pad">Nothing else is placed in the ${me.room} right now.</li>`}</ul>
          <div class="pinsection">Everyone else</div>` : nothing}
        <ul class="plain">${live.map((p) => row(p, false))}${quiet.map((p) => row(p, false))}</ul>
        ${rows.length ? nothing : html`<p class="muted small pad">No things yet.</p>`}
      </div>
    </div>`;
  }

  /** The chips and the ring over the full-screen stage. */
  _renderPinWhere() {
    const pin = this._pin, ent = pin.ent, name = this._label(ent), pn = this._pn(ent);
    const f = this._floorObj(), focus = this._pinFocus || {};
    const me = this._myPlace(), p = this._allRows().find((r) => r.ent === ent);
    const robot = !!this._robotOf(ent);
    // Your room, then the thing's, then the rest of the floor's rooms by name.
    const first = [me?.floor === this.floor ? me.room : null, p?.floor === this.floor ? p.zone : null].filter(Boolean);
    const rooms = [...new Set([...first, ...(f?.zones || []).filter((z) => !z.no_go && (z.cords || []).length >= 3).map((z) => z.entity_id).sort((a, b) => a.localeCompare(b))])]
      .filter((r) => (f?.zones || []).some((z) => z.entity_id === r));
    // The spots of the room in view first - that is where the finger is going.
    const roomPoly = (f?.zones || []).find((z) => z.entity_id === focus.room)?.cords;
    const centre = (pts) => ({ x: pts.reduce((a, q) => a + q.x, 0) / pts.length, y: pts.reduce((a, q) => a + q.y, 0) / pts.length });
    const inRoom = (sz) => roomPoly?.length >= 3 && pointInPolygon(centre(sz.cords), roomPoly) ? 0 : 1;
    const spots = (f?.subzones || []).filter((s) => (s.cords || []).length >= 3)
      .sort((a, b) => inRoom(a) - inRoom(b) || String(a.entity_id).localeCompare(String(b.entity_id))).map((s) => s.entity_id);
    const chip = (label, on, onClick, cls = "") => html`<button class="pinchip ${cls} ${on ? "on" : ""}" aria-pressed=${on} @click=${onClick}>${label}</button>`;
    const go = (next) => () => { this._pinFocus = next; this._pinZoom(); this.requestUpdate(); };
    const at = this._pinAt;
    const under = at ? (at.spot ? `${at.spot} · ${at.room || this.floor}` : (at.room || `Off the rooms · ${this.floor}`)) : this.floor;
    return html`
      <div class="pintop">
        <div class="pinbar top">
          <button class="iconbtn round" title="Back" aria-label="Back to the list" @click=${() => { this._pin = { step: "who" }; }}><ha-icon icon="mdi:arrow-left"></ha-icon></button>
          <div class="grow"><div class="muted small">Quick pin · 2 of 2 · ${this.floor}</div><h3>${robot ? `Where is ${name}'s dock?` : `Where is ${name} really?`}</h3></div>
        </div>
        <div class="pinchips">${rooms.map((r) => chip(r, !focus.spot && focus.room === r, go({ room: r })))}${chip("Whole floor", !focus.spot && !focus.room, go({}))}</div>
        ${spots.length ? html`<div class="pinchips spots">${spots.map((s) => chip(s, focus.spot === s, go({ spot: s, room: focus.room }), "spot"))}</div>` : nothing}
      </div>
      <div class="pinring" aria-hidden="true"><span class="n"></span><span class="s"></span><span class="w"></span><span class="e"></span><span class="dot"></span></div>
      <div class="pinhint">Drag the plan until the ring is on ${robot ? "the dock" : pn.obj}</div>
      <div class="pinunder">${under}</div>
      <div class="pinbar bottom">
        <button class="pinplace" ?disabled=${!!pin.busy} @click=${() => this._pinPlace()}><ha-icon icon=${robot ? "mdi:home-import-outline" : "mdi:map-marker-check"}></ha-icon>${robot ? `Mark ${name}'s dock here` : `Pin ${name} here`}</button>
      </div>`;
  }

  _renderPinDone() {
    const pin = this._pin, ent = pin.ent, name = this._label(ent), pn = this._pn(ent), t = pin.result;
    const rows = (t?.rows || []).slice(0, 6), best = rows[0];
    const where = pin.spot ? `${pin.spot} · ${pin.room || this.floor}` : (pin.room || this.floor);
    return html`<div class="pinsheet" role="dialog" aria-label="Quick pin: done">
      <div class="pinhead">
        <span class="pincheck"><ha-icon icon="mdi:check"></ha-icon></span>
        <div><div class="muted small">Pin ${t.mark.id} · from ${t.mark.samples} cycle${t.mark.samples === 1 ? "" : "s"}</div><h3>${name} · ${where}</h3></div>
      </div>
      <div class="pinbody">
        ${rows.length ? html`
          <p class="muted small pad">The last few minutes re-solved under each setting. Error is the mean distance from the pin; Room is how often the fix landed in the pin's room.</p>
          <table class="small pintable"><tr><th>Estimator</th><th class="num">Gain</th><th class="num">Error</th><th class="num">Room</th></tr>
            ${rows.map((r, i) => html`<tr class=${i === 0 ? "best" : ""}><td>${r.estimator}${r.estimator === "fused" ? ` ${Math.round(r.weight * 100)}%` : ""}</td><td class="num">×${fmtNum(r.gain, 1)}</td><td class="num">${fmtLen(r.mean_m, this.hass)}</td><td class="num">${Math.round(r.room_ok * 100)}%</td></tr>`)}
          </table>
          <p class="muted small pad">Top row: the fit that puts ${pn.obj} closest to your pin. One pin can overfit: pin ${pn.obj} in another room too.</p>`
        : html`<p class="muted small pad">Nothing could be re-solved for this pin: ${name} ${pn.has} not been heard from in the last few minutes. The pin is kept as a fingerprint reference.</p>`}
      </div>
      <div class="pinbar bottom stack">
        ${best ? html`<button class="pinplace" @click=${async () => { await this._applyRow(ent, best); this._endPin(); }}><ha-icon icon="mdi:check-all"></ha-icon>Apply best fit to ${name}</button>` : nothing}
        <div class="pinpair">
          <button class="pinsecondary" @click=${() => { this._pin = { step: "who" }; }}>Pin another</button>
          <button class="pinsecondary" @click=${() => this._pinUndo()}>Undo pin</button>
          <button class="pinsecondary" @click=${() => this._endPin()}>Done</button>
        </div>
      </div>
    </div>`;
  }

  /** Where the selected thing spent the last `hours`, binned per floor (see heatCells). */
  async _loadHeat(ent, hours) {
    this._heatHours = hours;
    if (hours) this._lastHeatHours = hours;
    if (!ent || !hours || !this._isAdmin()) { this._heat = null; return; }
    try {
      const now = Date.now() / 1000;
      const r = await this.hass.callWS({ type: "sextant/history/get", entity: ent, from: now - hours * 3600, max_points: 20000 });
      if (this._selected !== ent || this._heatHours !== hours || !this._isAdmin()) return;
      const points = (r.t || []).map((t, i) => ({
        t, x: r.x_m[i], y: r.y_m[i], gap: r.gap?.[i] || 0,
        f: typeof r.f?.[i] === "number" ? r.floors?.[r.f[i]] : r.f?.[i],
      }));
      this._heat = { ent, hours, keptSecs: r.config?.max_age || null, byFloor: heatCells(points, Math.min(now, r.to || now)) };
    } catch (e) {
      this._heat = null;
      toast(this, `history: ${e?.message || e}`);
    }
  }

  _pushHeat() {
    const f = this._floorObj(), h = this._heat;
    const mine = h && h.ent === this._selected ? h.byFloor[this.floor] : null;
    if (!mine || !f?.scale) { this._map?.setHeat(null); return; }
    this._map?.setHeat({ size: mine.cellM * f.scale, max: mine.max, cells: mine.cells.map((c) => ({ x: c.x * f.scale, y: c.y * f.scale, secs: c.secs })) });
  }

  _renderHeat(sel) {
    if (!this._isAdmin()) return nothing;
    const h = this._heat?.ent === sel.ent ? this._heat : null;
    const here = h?.byFloor[this.floor];
    const elsewhere = h ? Object.entries(h.byFloor).filter(([f]) => f !== this.floor).map(([f, v]) => `${f} ${shortSpan(v.total)}`) : [];
    return html`<div class="row heat">
      ${uiSegmented({ label: "Location heatmap", value: this._heatHours || 0, options: [{ value: 0, label: "Off" }, { value: 6, label: "6h", title: "Where it has been in the last 6 hours" }, { value: 24, label: "24h", title: "The last 24 hours" }, { value: 168, label: "7d", title: "The last 7 days" }], onChange: (v) => this._loadHeat(sel.ent, Number(v)) })}
      ${h ? html`<span class="muted small">${here ? html`${shortSpan(here.total)} on this floor, longest ${shortSpan(here.max)} in one place (red)` : "Not on this floor"}${elsewhere.length ? html` · ${elsewhere.join(", ")}` : nothing}${h.keptSecs && h.hours * 3600 > h.keptSecs + 60 ? html` · history only goes back ${shortSpan(h.keptSecs)}` : nothing}</span>` : nothing}
    </div>`;
  }

  _pushMarks() {
    const mine = this._selected ? this._marks.filter((m) => m.floor === this.floor) : [];
    this._map?.setMarks(mine.map((m) => ({ x: m.x, y: m.y, label: `mark ${m.id}` })));
  }

  /** The map click while marking: record where the selected thing really is, then evaluate. */
  _placeMark(m) {
    if (!this._marking || !this._selected) return false;
    this._marking = false;
    const ent = this._selected;
    const vacuum = this._robotOf(ent);
    if (vacuum) {
      (async () => {
        const r = await callWS(this, this.hass, { type: "sextant/robot/dock", vacuum, floor: this.floor, x: m.x, y: m.y });
        if (!r) return;
        const f = r.fit;
        toast(this, f ? `Dock marked: ${f.pairs.length} points agree to ${fmtNum(f.rms_m, 2)} m` : "Dock marked");
        this.dispatchEvent(new CustomEvent("layout-changed"));
      })();
      return true;
    }
    (async () => {
      const r = await callWS(this, this.hass, { type: "sextant/truth/mark", entity: ent, floor: this.floor, x: m.x, y: m.y });
      if (!r) return;
      this._truth = r;
      toast(this, `Pin ${r.mark.id} recorded from ${r.mark.samples} cycles`);
      this._loadMarks(ent);
      this.dispatchEvent(new CustomEvent("layout-changed"));
    })();
    return true;
  }

  async _deleteMark(id) {
    if (!confirmDialog(`Forget pin ${id}?`)) return;
    const r = await callWS(this, this.hass, { type: "sextant/truth/delete", mark_id: id });
    if (r) { if (this._truth?.mark?.id === id) this._truth = null; this._loadMarks(this._selected); }
  }

  async _applyRow(ent, row) {
    const r = await callWS(this, this.hass, { type: "sextant/truth/apply", entity: ent, weight: row.weight, gain: row.gain });
    if (r) { toast(this, `${this._label(ent)}: ${r.estimator}${r.estimator === "fused" ? ` at ${Math.round(r.fp_weight * 100)}% fingerprint` : ""}, gain ×${fmtNum(r.thing_gain, 2)}`); this._blend = null; this.dispatchEvent(new CustomEvent("layout-changed")); }
  }

  /** The blend in force for a thing, 0..1: its own weight, else what the tuning means. */
  _blendOf(ent) {
    const own = this.data?.layout?.thing_fp_weights?.[ent];
    if (typeof own === "number") return own;
    const est = this.data?.layout?.thing_estimators?.[ent] || this.data?.layout?.tuning?.position_estimator || "geometric";
    return est === "geometric" ? 0 : est === "fingerprint" ? 1 : (this.data?.layout?.tuning?.fingerprint_weight ?? 0.5);
  }

  async _setBlend(ent, value) {
    const r = await callWS(this, this.hass, { type: "sextant/thing/tune", entity: ent, fp_weight: value });
    if (r) { this._blend = null; this.dispatchEvent(new CustomEvent("layout-changed")); }
  }

  async _loadLinks() {
    const r = await this.hass.callWS({ type: "sextant/beacon_links" }).catch(() => null);
    if (r) this._links = r.beacons || [];
  }

  willUpdate(changed) {
    // Where people have been is for administrators. If this user is not one
    // (or stops being one while the page is open), drop anything already
    // loaded; the loaders below also discard answers that arrive afterwards.
    if (changed.has("hass") && !this._isAdmin() &&
        (this._timeline || this._marks.length || this._truth || this._history || this._heat || this._scrub != null || this._pin || this._wifiHeat)) {
      this._timeline = null; this._marks = []; this._truth = null;
      this._history = null; this._scrub = null; this._heat = null; this._heatHours = 0;
      this._pin = null;
      this._wifiHeat = null; this._wifiHeatKey = null; this._map?.setWifiHeat(null);
      this._map?.clearTrails();
    }
    // The map step takes the whole screen: the stage goes fixed and the
    // rest of the page hides under it (see :host(.pinning) in the styles).
    if (changed.has("_pin")) this.classList.toggle("pinning", this._pin?.step === "where");
  }

  updated(changed) {
    if (!this._map) return;
    if (changed.has("_mapOpen")) this._restoreDetailHeight();
    if (changed.has("data") || changed.has("floor")) this._pushFloor();
    if (changed.has("positions") || changed.has("floor") || changed.has("data") || changed.has("_scrub") || changed.has("_history")) this._pushThings();
    if (changed.has("hass")) this._map.setAreas(this.hass?.areas);
    if (changed.has("floor") || changed.has("_marks")) this._pushMarks();
    if (changed.has("floor") || changed.has("_heat") || changed.has("data")) this._pushHeat();
    if (changed.has("_options")) this._map.setOptions(this._options);
    if (changed.has("data")) this._map.setOptions({ staleAfter: this._staleAfter() });
    if (changed.has("_options") || changed.has("floor") || changed.has("data") || changed.has("hass")) {
      // Reloaded only when what it depends on moved: on or off, the floor,
      // and the floor's scale (the cells are in plan pixels at that scale).
      // A label or trails switch is not a reason to ask again.
      const on = !!this._options.wifi_heat && this._isAdmin();
      const key = on ? `${this.floor}|${this._floorObj()?.scale ?? ""}|${this._wifiBand() || ""}` : null;
      if (key !== this._wifiHeatKey) {
        this._wifiHeatKey = key;
        if (on) this._loadWifiHeat(); else { this._wifiHeat = null; this._map.setWifiHeat(null); }
      }
    }
    if (changed.has("data")) this._map.setAccessPoints(Array.isArray(this.data?.access_points) ? this.data.access_points : null);
    // A stay grows every cycle; re-read the timeline once a minute while a thing is focused.
    if (changed.has("positions") && this._selected && (!this._timeline || Date.now() - this._timeline.at > 60000)) this._loadTimeline(this._selected);
  }

  _floorObj() { return (this.data?.layout?.floor || []).find((f) => f.name === this.floor) || null; }

  _pushFloor() {
    const f = this._floorObj();
    if (f) for (const r of f.receivers || []) r.label = proxyName(this.data, r.address || r.entity_id);
    this._map.setFloor(f, mapUrlFor(this.floor, this.data?.maps));
    this._map.setOffline(this.positions?.offline_receivers || this.data?.offline_receivers || []);
    this._map.setOptions({ ...this._options, focus: this._selected });
  }

  _icon(ent) {
    const src = this.data?.layout?.thing_icons?.[ent];
    if (!src) return null;
    let img = this._icons.get(src);
    if (!img) { img = new Image(); img.src = src.startsWith("/") ? src : `/sextant/${src}`; img.onload = () => this._map?.invalidate(); this._icons.set(src, img); }
    return img;
  }

  _pushThings() {
    const rows = (this.positions?.positions || []).filter((p) => p.floor === this.floor);
    const classes = this.data?.layout?.thing_classes || {};
    const colors = this.data?.layout?.thing_colors || {};
    let things = rows.map((p) => ({ ...p, icon: this._icon(p.ent), mdi: classIcon(classes[p.ent]), color: colors[p.ent] || null, label: this._label(p.ent) }));
    // Scrubbing: replace the live dot of the scrubbed thing with the past one.
    const h = this._history;
    if (h && this._scrub != null && h.ent) {
      const f = this._floorObj();
      const at = this._pointAt(h, this._scrub);
      things = things.filter((t) => t.ent !== h.ent);
      if (at && at.f === this.floor && f?.scale) {
        things.push({ ent: h.ent, cords: [at.x * f.scale, at.y * f.scale], zone: at.z, conf: 1, label: `${this._label(h.ent)} · ${new Date(this._scrub * 1000).toLocaleTimeString()}`, icon: this._icon(h.ent), mdi: classIcon(classes[h.ent]), color: colors[h.ent] || null });
      }
      this._map.clearTrails();
      if (f?.scale) {
        const pts = h.points.filter((q) => q.f === this.floor && q.t <= this._scrub).map((q) => [q.x * f.scale, q.y * f.scale]);
        this._map.setTrail(h.ent, pts);
      }
    }
    this._map.setThings(things);
    this._map.setOffline(this.positions?.offline_receivers || []);
    // mmWave targets on this floor: the map draws the ones no thing claimed.
    this._map.setRadarTargets((this.positions?.radar_targets || []).filter((t) => t.floor === this.floor));
  }

  _label(ent) { return thingName(this.data, ent); }

  /**
   * The list, grouped by whose things they are: each Home Assistant person
   * gets a header (their picture, their name, and under it where their own
   * location sensor puts them) that folds the group away; the rest follow.
   * One thing is enough for a section - a person is tracked as a person -
   * except a pet whose one thing is its own tag (Meg over Meg says nothing).
   */
  /** Click a proxy on the map: what it is and what it is doing. */
  async _openProxy(index) {
    const f = (this.data?.layout?.floor || []).find((x) => x.name === this.floor);
    const rx = (f?.receivers || [])[index];
    if (!rx?.entity_id) return;
    this._proxy = { slug: rx.entity_id, loading: true };
    try {
      // Straight to hass: the helper turns a failure into null, which would
      // read as a proxy that publishes nothing rather than as an error.
      const info = await this.hass.callWS({ type: "sextant/proxy/info", proxy: rx.entity_id });
      if (this._proxy?.slug === rx.entity_id) this._proxy = { ...info, slug: rx.entity_id };
    } catch (e) {
      this._proxy = { slug: rx.entity_id, error: e?.message || String(e) };
    }
  }

  /** The proxy card: what it is, how it is, and what it is filtering out. */
  _renderProxyCard() {
    const p = this._proxy;
    if (!p) return nothing;
    const f = p.facts || {};
    // Numbers as a person would write them, and firmware without the build
    // stamp ESPHome appends.
    const val = (key, unit) => {
      const v = f[key];
      if (!v || ["unknown", "unavailable"].includes(v.state)) return null;
      const n = Number(v.state);
      // Whole numbers throughout: a proxy at 77.7 % says nothing 78 does not,
      // and a drop rate to the tenth of a percent is noise.
      const text = Number.isFinite(n) && v.state.trim() !== ""
        ? fmtNum(n, 0)
        : v.state.split(" (")[0];
      return unit === false ? text : `${text}${v.unit ? ` ${v.unit}` : ""}`;
    };
    const d = p.device || {};
    // No Wi-Fi signal to report means it is wired.
    const wired = !f.wifi_signal;
    // The proxies report the percentage ESPHome makes from dBm:
    // pct = clamp(2 * (dBm + 100)), so 80 % is -60 dBm and 66 % is -67, the
    // usual line between reliable and not. Wired is always good.
    const pct = Number(f.wifi_signal?.state);
    const dbm = Number.isFinite(pct) ? pct / 2 - 100 : null;
    const grade = wired ? "good" : !Number.isFinite(pct) ? "" : pct >= 80 ? "good" : pct >= 66 ? "fair" : "poor";
    // What the link is, in as few words as carry information: the band when
    // it is the interesting part (5 GHz is the rare one), else the 802.11
    // generation the proxy negotiated, else just Wi-Fi.
    // 2.4 GHz is channels 1-14 and 5 GHz starts at 32, so the channel says
    // which band it is; no proxy needs a sensor for that.
    const channel = Number(f.channel?.state);
    const band = Number.isFinite(channel) && channel > 0 ? (channel > 14 ? "5GHz" : "2.4GHz") : null;
    const generation = (val("generation", false) || "").split(" (")[0];
    const linkText = wired ? "Ethernet"
      : band && band.startsWith("5") ? `Wi-Fi ${band}`
      : generation || "Wi-Fi";
    const linkTitle = wired ? "Wired to the network"
      : [dbm == null ? "On Wi-Fi" : `Wi-Fi ${fmtNum(pct, 0)} % (${fmtNum(dbm, 0)} dBm)`,
         band, val("generation", false), val("channel") ? `channel ${val("channel")}` : null].filter(Boolean).join(" · ");
    const rows = [
      ["ESPHome release", val("esphome_version", false)],
      // The board name is ESPHome's project name, so it belongs with the version.
      // The version joins its parts with +; a space lets the ble half wrap.
      ["Project", [val("project_name", false) || d.board, (val("project_version", false) || "").replace(/\+/g, " ")].filter(Boolean).join(" ") || null],
      ["Uptime", val("uptime", false)],
      ["Hearing", p.heard == null ? null : `${p.heard} thing${p.heard === 1 ? "" : "s"}`],
      ["Adverts forwarded", val("adverts_forwarded")],
      ["Adverts ignored", [val("adverts_dropped"), val("drop_rate") ? `(${val("drop_rate")})` : null].filter(Boolean).join(" ") || null],
      ["IRKs installed", val("irks_loaded")],
      ["Wi-Fi", [val("wifi_signal"), val("ssid", false), val("channel") ? `ch ${val("channel")}` : null].filter(Boolean).join(" · ") || null],
      ["Chip", [d.chip, val("temperature")].filter(Boolean).join(" · ") || null],
      // What HA records for the node is whichever link it is on: a proxy that
      // reports a Wi-Fi signal is on Wi-Fi, one that does not is wired.
      ["Bluetooth MAC", p.address || null],
      [val("wifi_signal") ? "Wi-Fi MAC" : "Ethernet MAC", d.wifi_mac || null],
      ["Chip MAC", val("chip_mac", false)],
    ].filter(([, v]) => v);
    return html`<div class="proxycard" @click=${(e) => e.stopPropagation()}>
      <h4>${proxyName(this.data, p.slug)}${p.loading || p.error ? nothing : html`<span class="link ${grade}" title=${linkTitle}>
        <ha-icon icon=${wired ? "mdi:ethernet" : "mdi:wifi"}></ha-icon>${linkText}</span>`}</h4>
      ${p.loading ? html`<div class="muted small">Asking…</div>`
        : p.error ? html`<div class="warn small">${p.error}</div>`
        : rows.length ? html`<dl>${rows.map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>`
        : html`<div class="muted small">This proxy publishes nothing about itself.</div>`}
    </div>`;
  }

  /** How long a thing has been where it is, from its own location sensor
   * (which changes when its room or spot does), as (short, exact) or null. */
  _hereFor(p) {
    // Sextant's own answer first: it survives a restart, where the sensor's
    // last_changed is the restart itself. The spot when it is in one.
    const own = p.sub_zone && p.sub_zone !== "unknown" ? (p.spot_since ?? p.since) : p.since;
    let at = typeof own === "number" ? own : null;
    if (at == null) {
      const st = this.hass?.states?.[`sensor.${p.ent}_sextant_location`];
      if (!st || ["unknown", "unavailable"].includes(st.state)) return null;
      at = Date.parse(st.last_changed) / 1000;
    }
    if (!at) return null;
    return [shortAge(Math.max(0, Date.now() / 1000 - at)), this._since(at)];
  }

  /** When a thing was last heard, written as a point in time: the clock for
   * today, the date for longer ago, the year only past one. */
  _since(at) {
    if (!at) return null;
    const d = new Date(at * 1000), ago = Date.now() / 1000 - at;
    if (ago < 86400) return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    if (ago < 365 * 86400) return d.toLocaleDateString(undefined, { month: "numeric", day: "numeric" });
    return d.toLocaleDateString(undefined, { month: "numeric", day: "numeric", year: "2-digit" });
  }

  /** How long before a thing not heard from is called away rather than late. */
  _awayAfter() {
    const own = this.data?.layout?.tuning?.away_after_secs;
    const dflt = this.data?.tuning_spec?.away_after_secs?.default;
    return typeof own === "number" ? own : typeof dflt === "number" ? dflt : 900;
  }

  /** Every thing Sextant knows, not only the ones heard this cycle: a phone
   * that left the house still belongs in the list, shown where it was last
   * seen. The missing ones come from their own sensors. */
  _allRows() {
    const live = (this.positions?.positions || []).slice();
    const seen = new Set(live.map((p) => p.ent));
    const known = Object.keys(this.data?.layout?.thing_classes || {});
    for (const ent of known) {
      if (seen.has(ent)) continue;
      const loc = this.hass?.states?.[`sensor.${ent}_sextant_location`];
      const floor = this.hass?.states?.[`sensor.${ent}_sextant_floor`];
      const known_where = loc && !["unknown", "unavailable"].includes(loc.state);
      // Sextant remembers the last sighting across restarts, which the
      // sensors cannot: after one they read unknown, and their timestamp is
      // the restart, not a sighting. So that is the first answer, and the
      // sensors fill in for anything it has never heard.
      const last = this.data?.last_seen?.[ent];
      live.push({
        ent,
        away: true,
        updated: last?.updated ?? (known_where ? Date.parse(loc.last_changed) / 1000 : null),
        zone: last?.zone ?? (known_where ? (loc.attributes?.room || loc.state) : null),
        sub_zone: last?.spot ?? (known_where ? loc.attributes?.spot : null),
        floor: last?.floor ?? (floor && !["unknown", "unavailable"].includes(floor.state) ? floor.state : null),
      });
    }
    return live.sort((a, b) => this._label(a.ent).localeCompare(this._label(b.ent)));
  }

  /** live, waiting (heard, but not lately) or away (long gone, or not heard at all). */
  /** The vacuum entity a thing is placed from, when it is a robot (robots.py). */
  _robotOf(ent) {
    return (this.positions?.positions || []).find((p) => p.ent === ent)?.robot || null;
  }

  _state(p) {
    const st = staleness(p, this._staleAfter());
    if (p.away || (this._awayAfter() > 0 && st.age > this._awayAfter())) return { ...st, away: true, ghost: true };
    return { ...st, away: false };
  }

  _renderGroupedRows(rows) {
    const owners = this.data?.layout?.thing_owners || {};
    const byOwner = new Map();
    for (const p of rows) {
      const o = owners[p.ent];
      if (o) byOwner.set(o, [...(byOwner.get(o) || []), p]);
    }
    const same = (a, b) => String(a).trim().toLowerCase() === String(b).trim().toLowerCase();
    const groups = [...byOwner]
      .map(([person, list]) => ({ person, list, name: this.hass?.states?.[person]?.attributes?.friendly_name || person.slice(7) }))
      .filter((g) => g.list.length >= 2 || !same(this._label(g.list[0].ent), g.name))
      .sort((a, b) => a.name.localeCompare(b.name));
    if (!groups.length && !rows.some((p) => ["cat", "dog", "paw"].includes((this.data?.layout?.thing_classes || {})[p.ent]))) return rows.map((p) => this._renderRow(p));
    const grouped = new Set(groups.flatMap((g) => g.list.map((p) => p.ent)));
    // Then the pets (by class), then whatever is left.
    const classes = this.data?.layout?.thing_classes || {};
    const isPet = (p) => ["cat", "dog", "paw"].includes(classes[p.ent]);
    const pets = rows.filter((p) => !grouped.has(p.ent) && isPet(p));
    const rest = rows.filter((p) => !grouped.has(p.ent) && !isPet(p));
    const folded = this._folded || new Set();
    const fold = (key) => {
      const next = new Set(folded);
      if (next.has(key)) next.delete(key); else next.add(key);
      this._folded = next;
      try { localStorage.setItem("sextant.live.folded", JSON.stringify([...next])); } catch { /* ignore */ }
    };
    const header = (key, title, extra) => html`<li class="group ${extra.away ? "away" : ""}" @click=${() => fold(key)} role="button" aria-expanded=${!folded.has(key)}>
      <ha-icon class="chev" icon=${folded.has(key) ? "mdi:chevron-right" : "mdi:chevron-down"}></ha-icon>${extra.avatar || nothing}
      <span class="gtext"><span class="gname">${title}</span>${extra.where ? html`<span class="gwhere small">${extra.where}</span>` : nothing}</span></li>`;
    return html`${groups.map((g) => {
      const st = this.hass?.states?.[g.person], pic = st?.attributes?.entity_picture;
      const where = this.hass?.states?.[`sensor.${g.person.slice(7)}_sextant_person_location`]?.state;
      const avatar = html`<span class="gavatar">${pic ? html`<img src=${pic} alt="">` : g.name.slice(0, 2).toUpperCase()}</span>`;
      return html`${header(g.person, g.name, { avatar, where: where && where !== "unknown" ? where : "",
        away: g.list.every((p) => this._state(p).away) })}
        ${folded.has(g.person) ? nothing : g.list.map((p) => this._renderRow(p))}`;
    })}
    ${pets.length ? html`${header("_pets", "Pets", { avatar: html`<span class="gavatar"><ha-icon icon="mdi:paw"></ha-icon></span>` })}${folded.has("_pets") ? nothing : pets.map((p) => this._renderRow(p))}` : nothing}
    ${rest.length ? html`${header("_rest", "Everything else", {})}${folded.has("_rest") ? nothing : rest.map((p) => this._renderRow(p))}` : nothing}`;
  }

  _renderRow(p) {
    const st = this._state(p);
    const name = this._label(p.ent), pn = this._pn(p.ent);
    const lastSeen = st.age ? `Not heard for ${fmtAge(st.age)}: this is where ${name} ${pn.was} last placed` : `${name} has not been heard from`;
    return html`
            <li class="${p.ent === this._selected ? "selected" : ""} ${st.ghost ? "ghost" : ""} ${st.away ? "away" : ""}" title=${st.ghost ? lastSeen : ""} @click=${() => { this._select(p.ent === this._selected ? null : p.ent); if (p.floor && p.floor !== this.floor) this.dispatchEvent(new CustomEvent("floor-changed", { detail: p.floor })); }}>
              ${(() => {
                const who = this._speaksFor(p.ent);
                // Three states, one badge: away (long gone), waiting (heard,
                // but not lately), or the thing its owner is read from. A
                // thing not being heard cannot be any owner's source.
                const badge = st.away ? html`<ha-icon class="viabadge ghostbadge" icon="mdi:ghost-outline"></ha-icon>`
                  : st.ghost ? html`<ha-icon class="viabadge waitbadge" icon="mdi:timer-sand"></ha-icon>`
                  : who ? html`<ha-icon class="viabadge" icon="mdi:map-marker"></ha-icon>` : nothing;
                // A low battery gets its own corner: it is a separate question
                // from the status above, and both can be true at once - a tag
                // going quiet BECAUSE its battery is dying is the whole point.
                const battery = this._batteryBadge(p.ent);
                if (badge === nothing && battery === nothing) return this._avatar(p.ent);
                const why = badge === nothing ? "" : st.away ? lastSeen : st.ghost ? `Last heard ${fmtAge(st.age)} ago` : `Where ${who} is read from right now`;
                return html`<span class="avslot" title=${why}>${this._avatar(p.ent)}${badge}${battery}</span>`;
              })()}
              <span class="name">${this._label(p.ent)}</span>
              <span class="where">${p.zone ? html`${this._roomIcon(p.floor, p.zone) ? html`<ha-icon class="roomicon" icon=${this._roomIcon(p.floor, p.zone)}></ha-icon>` : nothing}${p.zone}` : html`<span class="muted">away</span>`}</span>
              ${(() => {
                const here = st.away || st.ghost ? null : this._hereFor(p);
                return html`<span class="muted small floorline" title=${here ? `Here since ${here[1]}` : ""}>${
                  st.away && this._since(p.updated) ? html`since ${this._since(p.updated)}${p.floor ? " · " : ""}`
                  : st.ghost && st.age ? html`seen ${shortAge(st.age)} ago${p.floor ? " · " : ""}` : nothing}${p.floor || (st.ghost ? nothing : "")}${
                  here ? html` · ${here[0]}` : nothing}</span>`;
              })()}
              ${p.sub_zone && p.sub_zone !== "unknown" ? html`<span class="spot muted small">${p.sub_zone}</span>` : nothing}
              ${p.ent === this._selected ? html`<div class="quickin" @click=${(e) => e.stopPropagation()}>${this._renderQuick(p)}</div>` : nothing}
            </li>`;
  }

  /** The person this thing is speaking for right now, or null: the owner's
   * location sensor names the thing it read (via). */
  _speaksFor(ent) {
    const owners = this.data?.layout?.thing_owners || {};
    const person = owners[ent];
    // Only where there is a choice to report: a pet owns its own tag, so its
    // person sensor only ever reads that tag back.
    if (!person || Object.values(owners).filter((o) => o === person).length < 2) return null;
    const st = this.hass?.states?.[`sensor.${person.split(".")[1]}_sextant_person_location`];
    if (st?.attributes?.via !== ent) return null;
    return this.hass?.states?.[person]?.attributes?.friendly_name || person.split(".")[1];
  }

  /** The icon of the Home Assistant area a room is linked to, or null. */
  _roomIcon(floorName, roomName) {
    const f = (this.data?.layout?.floor || []).find((x) => x.name === floorName);
    const areaId = (f?.zones || []).find((z) => z.entity_id === roomName)?.area_id;
    return (areaId && this.hass?.areas?.[areaId]?.icon) || null;
  }

  /** He, she, they or it for a thing (its setting, else its class; people and pets are never "it"). */
  _pn(ent) { return pronounsFor(this.data?.layout, ent); }

  /** The same disc the map draws: the thing's hue, with its custom icon, its class icon, or initials. */
  _avatar(ent) {
    const color = thingColor(ent, this.data?.layout?.thing_colors?.[ent]);
    const src = this.data?.layout?.thing_icons?.[ent];
    const mdi = classIcon(this.data?.layout?.thing_classes?.[ent]);
    return html`<span class="avatar" style="background: ${color}">
      ${src ? html`<img src=${src.startsWith("/") ? src : `/sextant/${src}`} alt="">` : mdi ? html`<ha-icon icon=${mdi}></ha-icon>` : html`<span class="initials">${this._label(ent).slice(0, 2).toUpperCase()}</span>`}
    </span>`;
  }

  _pointAt(h, t) {
    const pts = h.points;
    if (!pts.length) return null;
    let lo = 0, hi = pts.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (pts[mid].t <= t) lo = mid; else hi = mid - 1; }
    return pts[lo].t <= t ? pts[lo] : null;
  }

  /** The Wi-Fi signal map for this floor (heat.py), drawn as the switch says. */
  async _loadWifiHeat() {
    const floor = this.floor;
    if (!this._isAdmin()) return;
    const band = this._wifiBand();
    const r = await this.hass?.callWS({ type: "sextant/wifi/heat", floor, field: true, ...(band ? { band } : {}) }).catch(() => null);
    // Switched off, another floor, or admin gone, while it was on its way.
    if (!this._options.wifi_heat || floor !== this.floor || band !== this._wifiBand() || !this._isAdmin()) return;
    this._wifiHeat = r;
    this._pushWifiHeat();
  }

  _pushWifiHeat() {
    const r = this._wifiHeat;
    if (!r) { this._map?.setWifiHeat(null); return; }
    // Each access point its own colour, in a fixed order, so a colour means
    // the same access point on every floor and every visit.
    const macs = Object.keys(r.aps || {}).sort();
    for (const c of r.cells || []) if (!macs.includes(c.ap)) macs.push(c.ap);
    const colours = Object.fromEntries(macs.map((m, i) => [m, `hsla(${Math.round((i * 360) / Math.max(macs.length, 1) + 15) % 360}, 65%, 52%, 0.55)`]));
    this._wifiColours = colours;
    this._map?.setWifiHeat({ cells: r.cells || [], field: r.field?.grid || null, mode: this._wifiMode(), names: r.aps || {}, colours });
    this.requestUpdate();
  }

  /** The signal map's view: the estimated field unless measured or access
   * point was picked ("signal", the old name for measured, reads as it). */
  /** The band the signal map keeps to ("2.4", "5", "6"), or null for all. */
  _wifiBand() {
    const b = this._options.wifi_heat_band;
    return ["2.4", "5", "6"].includes(b) ? b : null;
  }

  /** What each band's model says, for the legend: "2.4 GHz ±6 dB, 5 GHz ±8 dB". */
  _wifiModelText(models) {
    const parts = Object.entries(models || {}).filter(([, m]) => m?.rms != null)
      .map(([b, m]) => (b === "mixed" ? `±${Math.round(m.rms)} dB (bands not told apart yet)` : `${b} GHz ±${Math.round(m.rms)} dB`));
    return parts.join(", ");
  }

  _wifiMode() {
    const m = this._options.wifi_heat_mode;
    return m === "ap" ? "ap" : m === "measured" || m === "signal" ? "measured" : "estimated";
  }

  _renderWifiLegend() {
    const r = this._wifiHeat;
    if (!this._options.wifi_heat || !r) return nothing;
    const mode = this._wifiMode(), byAp = mode === "ap";
    const cells = r.cells || [];
    const models = r.field?.models;
    const band = this._wifiBand();
    const bands = r.bands || [];
    const here = [...new Set(cells.map((c) => c.ap))].sort((a, b) => String(r.aps?.[a] || a).localeCompare(String(r.aps?.[b] || b)));
    return html`<div class="wifilegend ${this._history ? "lifted" : ""}">
      ${uiSegmented({ label: "Wi-Fi signal map", value: mode, options: [
        { value: "estimated", label: "Estimated", title: "The signal everywhere: a model of each placed access point fitted to what was measured, faded where it is only the model" },
        { value: "measured", label: "Measured", title: "Only where phones, watches and proxies have measured it" },
        { value: "ap", label: "Access point", title: "Which access point clients were on, where they measured it" }],
        onChange: (v) => { this._setOption("wifi_heat_mode", v); this._pushWifiHeat(); } })}
      ${bands.length > 1 || band ? uiSegmented({ label: "Band", value: band || "all", options: [
        { value: "all", label: "All", title: "Every band: the strongest access point and band at each point" },
        ...["2.4", "5", "6"].filter((b) => bands.includes(b) || b === band).map((b) => ({ value: b, label: `${b} GHz`, title: `Only ${b} GHz` }))],
        onChange: (v) => this._setOption("wifi_heat_band", v === "all" ? null : v) }) : nothing}
      ${mode === "estimated" && !r.field?.grid ? html`<div class="muted">${band && models && !models[band]
        ? `No estimate for ${band} GHz yet: it needs a dozen measured squares on that band. Showing what was measured.`
        : "No estimate: place the access points on the plan (Edit, Wi-Fi). Showing what was measured."}</div>` : nothing}
      ${!cells.length ? html`<div class="muted">No samples on this floor yet.</div>`
        : byAp ? html`<div class="apkeys">${here.map((m) => html`<span><i style=${`background:${this._wifiColours?.[m]}`}></i>${r.aps?.[m] || m}</span>`)}</div>`
        : html`<div class="ramp"><span>-80</span><i style=${`background: linear-gradient(90deg, ${[-80, -72, -65, -58, -50].map((d) => signalColour(d, 0.85)).join(", ")})`}></i><span>-50 dBm</span></div>`}
      ${cells.length ? html`<div class="muted">${mode === "estimated" && r.field?.grid
        ? html`Strong where measured, faded where only the model says${this._wifiModelText(models) ? html` · typical error ${this._wifiModelText(models)}` : nothing}`
        : html`${cells.length} measured square${cells.length === 1 ? "" : "s"} on this floor`} · point at the map, or tap it</div>` : nothing}
    </div>`;
  }

  _setOption(key, value) {
    this._options = { ...this._options, [key]: value };
    try { localStorage.setItem("sextant.live.options", JSON.stringify(this._options)); } catch { /* ignore */ }
  }

  async _loadHistory(ent) {
    if (!ent || !this._isAdmin()) { this._history = null; this._scrub = null; this._map?.clearTrails(); return; }
    try {
      const r = await this.hass.callWS({ type: "sextant/history/get", entity: ent, max_points: 3000 });
      if (!this._isAdmin()) return;   // access changed while this was in flight
      // f and z index into r.floors / r.zones (the record is a table of small ints).
      const points = (r.t || []).map((t, i) => ({
        t, x: r.x_m[i], y: r.y_m[i],
        f: typeof r.f?.[i] === "number" ? r.floors?.[r.f[i]] : r.f?.[i],
        z: typeof r.z?.[i] === "number" ? r.zones?.[r.z[i]] : r.z?.[i],
      }));
      this._history = { ent, from: r.from, to: r.to, points };
      this._scrub = r.to;
    } catch (e) {
      toast(this, `history: ${e?.message || e}`);
    }
  }

  render() {
    const rows = this._allRows();
    const sel = rows.find((p) => p.ent === this._selected);
    const h = this._history;
    const pinning = this._pin?.step === "where";
    const switches = [
      ["image", "Map image", "Show or hide the floor-plan drawing behind the rooms", "mdi:floor-plan"],
      ["labels", "Labels", "Room and thing names", "mdi:label-outline"],
      ["trails", "Trails", "Each thing's recent path", "mdi:shoe-print"],
      ["subzones", "Spots", "Draw the spots (a couch, a desk, a bedside table)", "mdi:sofa-outline"],
      ["receivers", "Proxies", "Draw the proxies. Whichever one you point at is named; Labels names the rooms and things", "mdi:access-point"],
      ["access_points", "Wi-Fi", "Draw the Wi-Fi access points placed on the plan. Point at one (or tap it) for its name and how many clients it has", "mdi:wifi"],
      ...(this._isAdmin() ? [["wifi_heat", "Signal", "The Wi-Fi signal map: how strong the signal is in each square metre, or which access point clients are on there, measured from the proxies and the people's phones and watches", "mdi:wifi-strength-3"]] : []),
      ["circles", "Range circles", "The distance each proxy measured, as a circle: the fix is where they meet", "mdi:radar"],
      ["fingerprint", "Fingerprint fix", "Where the fingerprint estimator alone would put each thing (dashed), next to the published fix", "mdi:fingerprint"],
    ];
    // The map's own switches, as the pressed buttons the Edit tools and a
    // thing's quick actions use: an icon with its word under it.
    const optBtn = ([k, label, tip, icon]) => html`<button class="qa opt ${this._options[k] ? "on" : ""}" title=${`${label}: ${tip}`}
      aria-label=${label} aria-pressed=${!!this._options[k]} @click=${() => this._setOption(k, !this._options[k])}>
      <ha-icon icon=${icon}></ha-icon><span>${label}</span></button>`;
    const gridPicker = uiSelect({ label: "Grid", value: this._options.grid, options: [{ value: "off", label: "No grid" }, { value: "m", label: "Metres" }, { value: "ft", label: "Feet" }], onChange: (v) => this._setOption("grid", v), style: "min-width: 120px" });
    // The grid as one button that steps No grid -> Metres -> Feet, so it sits in
    // the icon toolbar with everything else instead of a dropdown in the middle
    // of it. The narrow sheet keeps the dropdown, where there is room for words.
    const GRID = [["off", "No grid"], ["m", "Metres"], ["ft", "Feet"]];
    const gi = Math.max(0, GRID.findIndex(([v]) => v === this._options.grid));
    const [, gridName] = GRID[gi];
    const [nextGrid, nextName] = GRID[(gi + 1) % GRID.length];
    const gridBtn = html`<button class="qa opt ${this._options.grid && this._options.grid !== "off" ? "on" : ""}"
      title=${`Grid: ${gridName}. Click for ${nextName}`} aria-label=${`Grid: ${gridName}`}
      @click=${() => this._setOption("grid", nextGrid)}>
      <ha-icon icon=${this._options.grid && this._options.grid !== "off" ? "mdi:grid" : "mdi:grid-off"}></ha-icon>${this._options.grid && this._options.grid !== "off" ? html`<b class="unit">${this._options.grid}</b>` : nothing}</button>`;
    // Fit, in and out, as their own small cluster in the bottom corner - out of
    // the way of the switches, and where every map puts them.
    const zoom = html`<div class="zoom ${this._history ? "lifted" : ""}" role="group" aria-label="Zoom">
      <button title="Fit the whole floor into view" aria-label="Fit the whole floor" @click=${() => this._map.fit()}><ha-icon icon="mdi:fit-to-screen-outline"></ha-icon></button>
      <button title="Zoom in" aria-label="Zoom in" @click=${() => this._map.zoomBy(1.3)}><ha-icon icon="mdi:plus"></ha-icon></button>
      <button title="Zoom out" aria-label="Zoom out" @click=${() => this._map.zoomBy(1 / 1.3)}><ha-icon icon="mdi:minus"></ha-icon></button>
    </div>`;
    return html`
      <div class="quick-actions">
        ${uiButton({ label: "Self-test", kind: "outline", icon: "mdi:clipboard-check-outline", onClick: () => this._goto("proxies") })}
        ${this._isAdmin() ? html`
          ${uiButton({ label: "New thing", kind: "outline", icon: "mdi:plus-circle-outline", onClick: () => this._goto("things") })}
          ${uiButton({ label: "Calibrate", kind: "outline", icon: "mdi:tune-vertical", onClick: () => this._goto("calibration") })}` : nothing}
      </div>
      <div class="stage ${this._mapOpen || pinning ? "" : "collapsed"}"><canvas></canvas>${pinning ? this._renderPinWhere() : this._renderProxyCard()}
        <div class="overlay" role="toolbar" aria-label="Map">
          <div class="chips wide-only">${switches.map(optBtn)}</div>
          <span class="sep wide-only"></span>
          <span class="wide-only">${gridBtn}</span>
          <button class="iconbtn narrow-only" title="Map options" aria-label="Map options" @click=${() => { this._optionsOpen = !this._optionsOpen; }}><ha-icon icon="mdi:tune-variant"></ha-icon></button>
          <button class="iconbtn narrow-only" title="Hide the map" aria-label="Hide the map" @click=${() => { this._mapOpen = false; }}><ha-icon icon="mdi:map-minus"></ha-icon></button>
        </div>
        ${zoom}
        ${pinning ? nothing : this._renderWifiLegend()}
        ${this._optionsOpen ? html`
          <div class="opts-backdrop narrow-only" @click=${() => { this._optionsOpen = false; }}></div>
          <div class="opts-sheet narrow-only">
            <h3>Map options</h3>
            <div class="chips optgrid">${switches.map(optBtn)}</div>
            ${gridPicker}
            ${uiButton({ label: "Done", kind: "primary", onClick: () => { this._optionsOpen = false; } })}
          </div>` : nothing}
        ${h ? html`
          <div class="scrub">
            <span>${new Date(h.from * 1000).toLocaleTimeString()}</span>
            <input type="range" min=${h.from} max=${h.to} step="1" .value=${String(this._scrub ?? h.to)}
                   @input=${(e) => { this._scrub = Number(e.target.value); }}>
            <span>${new Date(h.to * 1000).toLocaleTimeString()}</span>
            ${uiButton({ label: "Back to live", kind: "text", onClick: () => this._loadHistory(null) })}
          </div>` : nothing}
      </div>
      <aside class="side">
        <h3>Things <span class="muted">${rows.length}</span>
          <span class="narrow-only maptoggle">${uiButton({
            label: this._mapOpen ? "Hide map" : "Show map",
            icon: this._mapOpen ? "mdi:map-minus" : "mdi:map-outline",
            kind: "text",
            onClick: () => { this._mapOpen = !this._mapOpen; },
          })}</span>
        </h3>
        <ul class="list">
          ${this._renderGroupedRows(rows)}
          ${rows.length ? nothing : html`<li class="muted">No positions yet.</li>`}
        </ul>
      </aside>
        ${sel ? html`
          <div class="card detail ${this._history ? "lifted" : ""}">
            <div class="grip narrow-only" role="separator" tabindex="0" aria-orientation="horizontal"
                 aria-label="Resize the details: drag, or arrow keys; Backspace resets"
                 aria-valuemin=${SextantLive.DETAIL_MIN} aria-valuemax=${this._detailMax()} aria-valuenow=${this._detailHeight() ?? nothing}
                 @pointerdown=${(e) => this._gripDown(e)} @pointermove=${(e) => this._gripMove(e)} @pointerup=${(e) => this._gripUp(e)} @pointercancel=${(e) => this._gripUp(e)}
                 @keydown=${(e) => this._gripKey(e)} @dblclick=${() => this._setDetailHeight(null)}><span></span></div>
            <h4>${this._label(sel.ent)}<span class="grow"></span>
              <span class="iconbar">
                ${/* Three states in the first slot. Away: nothing is here to
                      correct and it may never be, so Forget. Quiet (not heard
                      for a while, but not gone): there is nothing recent to
                      re-solve, so the slot shows why, greyed. Live: "here". */ ""}
                ${sel.robot
                  ? uiIconButton({ icon: "mdi:home-import-outline", active: this._marking, title: this._marking ? `Marking ${this._label(sel.ent)}'s dock - tap the plan` : `Mark the dock: tap where ${this._label(sel.ent)}'s dock is. It is the most trusted point when its map is lined up with this floor`, onClick: () => { this._marking = !this._marking; } })
                  : this._state(sel).away
                  ? uiIconButton({ icon: "mdi:delete-outline", title: `Forget ${this._label(sel.ent)}: remove ${this._pn(sel.ent).poss} last sighting, history and - if nothing tracks ${this._pn(sel.ent).obj} any more - settings`, onClick: () => this._forget(sel.ent) })
                  : this._state(sel).ghost
                    ? uiIconButton({ icon: "mdi:timer-sand", disabled: true, title: `Not heard for ${fmtAge(this._state(sel).age)}: nothing recent to correct. "${this._label(sel.ent)} is actually here…" comes back once ${this._pn(sel.ent).subj} ${this._pn(sel.ent).is} heard again`, onClick: () => {} })
                    : uiIconButton({ icon: "mdi:map-marker-check", active: this._marking, title: this._marking ? `Marking where ${this._label(sel.ent)} really is - tap the plan` : `${this._label(sel.ent)} is actually here… Tell Sextant where ${this._pn(sel.ent).subj} really ${this._pn(sel.ent).is}; the last few minutes are re-solved under every setting to show which fits best`, onClick: () => { this._marking = !this._marking; } })}
                ${this._isAdmin() ? uiIconButton({ icon: "mdi:pencil-outline", title: `Edit ${this._label(sel.ent)}: name, class, icon, owner`, onClick: () => this._goto({ mode: "things", thing: sel.ent }) }) : nothing}
                ${this._isAdmin() ? uiIconButton({ icon: "mdi:history", title: `Scrub history: replay where ${this._label(sel.ent)} has been on the plan`, disabled: h?.ent === sel.ent, onClick: () => this._loadHistory(sel.ent) }) : nothing}
                <button class="iconbtn" title="Close" aria-label="Close" @click=${() => this._select(null)}><ha-icon icon="mdi:close"></ha-icon></button>
              </span></h4>
            <dl>
              <dt>Room</dt><dd>${sel.zone} ${sel.zone_locked ? html`<ha-icon icon="mdi:lock" title="stationary lock: still for a while, so the room holds"></ha-icon>` : nothing}</dd>
              <dt>Spot</dt><dd>${sel.sub_zone && sel.sub_zone !== "unknown" ? sel.sub_zone : "—"}</dd>
              <dt>Floor</dt><dd>${sel.floor}</dd>
              ${sel.robot ? html`<dt>Placed from</dt><dd>its own map <span class="muted small">(${this.hass?.states?.[sel.robot]?.state || sel.robot_state || "unknown"}; the map fits this floor to ${fmtLen(sel.rms_m, this.hass)})</span></dd>` : html`<dt>Proxies</dt><dd>${sel.radii?.length ?? 0} in the solve${sel.anchor ? html`<br><span class="pill ok" title=${`one proxy reads ${this._label(sel.ent)} within arm's reach and no other comes close: placed on that proxy`}>anchored to ${proxyName(this.data, sel.anchor)}</span>` : nothing}${sel.radar ? html`<br><span class="pill ok" title=${`an mmWave sensor sees someone where Bluetooth puts ${this._label(sel.ent)}: placed on the radar's target, to a few tens of centimetres`}>placed by ${sel.radar}</span>` : nothing}</dd>`}
              ${this._renderHere(sel)}
              ${this._battery(sel.ent) === null ? nothing : html`<dt>Battery</dt><dd class=${this._battery(sel.ent) <= BATTERY_CRITICAL ? "crit" : this._battery(sel.ent) <= BATTERY_LOW ? "warn" : ""}>${Math.round(this._battery(sel.ent))}%</dd>`}
              <dt>Updated</dt><dd>${typeof sel.updated === "number" && sel.updated > 0 ? html`${fmtAge(Date.now() / 1000 - sel.updated)} ago` : html`<span class="muted">not heard since the last restart</span>`}${staleness(sel, this._staleAfter()).ghost ? html` <span class="pill warn" title=${`Nothing has heard ${this._label(sel.ent)} since; this is where ${this._pn(sel.ent).subj} ${this._pn(sel.ent).was} last placed`}>not heard</span>` : nothing}</dd>
            </dl>
            ${this._renderTimeline(sel)}
            ${sel.robot ? nothing : html`<details class="telemetry">
              <summary>Confidence <span class="muted small">how sure Sextant is, and why</span></summary>
              <dl>
                <dt>Floor odds</dt><dd>${sel.floors ? Object.entries(sel.floors).sort((a, b) => b[1] - a[1]).map(([f, p]) => `${f} ${(p * 100).toFixed(0)}%`).join(" · ") : "—"}</dd>
                <dt>Spot shares</dt><dd>${sel.sub_zones ? Object.entries(sel.sub_zones).sort((a, b) => b[1] - a[1]).map(([s, p]) => `${s === "unknown" ? "none" : s} ${(p * 100).toFixed(0)}%`).join(" · ") : "—"}</dd>
                <dt>Confidence</dt><dd>${sel.conf ?? "—"}${sel.rms_m != null ? html` <span class="muted small">rms ${fmtLen(sel.rms_m, this.hass)}</span>` : nothing}</dd>
                <dt>Estimator</dt><dd>${sel.estimator || "geometric"}${sel.fp ? html` <span class="muted small">fp ${sel.fp.conf}${sel.fp.gain != null ? ` · gain ×${sel.fp.gain}` : ""} · ${(sel.fp.refs || []).map((r) => proxyName(this.data, r[0])).slice(0, 2).join(", ")}</span>` : nothing}</dd>
                <dt>Trust</dt><dd>${sel.fp?.trust != null ? `${Math.round(sel.fp.trust * 100)}%` : "—"} <span class="muted small">${sel.fp?.ratio != null ? `ratio ${fmtNum(sel.fp.ratio, 2)}` : ""}</span></dd>
                <dt>Speed</dt><dd>${fmtSpeed(sel.speed, this.hass)}</dd>
              </dl>
            </details>`}
            ${this._renderHeat(sel)}
            ${sel.robot ? nothing : this._renderBlend(sel)}
            ${sel.robot ? nothing : this._renderTruth(sel)}
            ${sel.robot ? nothing : this._renderLinks(sel.ent)}
          </div>` : nothing}
        ${this._isAdmin() && !this._pin && !sel ? html`
          <button class="pinfab narrow-only" title="Quick pin: say where a thing really is" @click=${() => this._startPin()}>
            <ha-icon icon="mdi:map-marker-check"></ha-icon><span>Pin</span></button>` : nothing}
        ${this._pin?.step === "who" ? this._renderPinWho() : this._pin?.step === "done" ? this._renderPinDone() : nothing}
    `;
  }

  /** The stays from the timeline, with the current one reaching to now while it is still heard. */
  _stays(sel) {
    const tl = this._timeline;
    if (!tl || tl.failed || tl.ent !== sel.ent) return null;
    const stays = (tl.stays || []).map((s) => ({ ...s }));
    const last = stays[stays.length - 1];
    const heard = !staleness(sel, this._staleAfter()).ghost;
    if (last && !last.unheard && heard) last.end = Math.max(last.end, Date.now() / 1000);
    return stays;
  }

  /** The thing's battery level (0-100), or null when it has no battery sensor
   * or the sensor has nothing to say. */
  _battery(ent) {
    const id = this.data?.layout?.thing_battery_entity?.[ent];
    const v = id ? parseFloat(this.hass?.states?.[id]?.state) : NaN;
    return Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : null;
  }

  /** A badge only once the battery is low: a full one would put a badge on
   * every pet and say nothing. Amber from BATTERY_LOW, red from BATTERY_CRITICAL. */
  _batteryBadge(ent) {
    const level = this._battery(ent);
    if (level === null || level > BATTERY_LOW) return nothing;
    const crit = level <= BATTERY_CRITICAL;
    return html`<ha-icon class="batterybadge ${crit ? "crit" : ""}" icon=${crit ? "mdi:battery-alert-variant-outline" : "mdi:battery-low"}
      title=${`Battery ${Math.round(level)}%${crit ? " - replace it soon; a dead tag reads exactly like one that has left" : ""}`}></ha-icon>`;
  }

  /** "Meg's Cafe for 1h 12m · in Catwalk for 3h" - how long it has been where it is. */
  _renderHere(sel) {
    // A thing nothing is hearing is not "here" anywhere, and certainly has not
    // "just arrived": say where it was last heard, if that is known at all.
    if (sel.away) {
      const where = (sel.sub_zone && sel.sub_zone !== "unknown" ? sel.sub_zone : null) || sel.zone;
      return where ? html`<dt>Last heard</dt><dd>${where}${sel.floor ? html` <span class="muted small">${sel.floor}</span>` : nothing}</dd>` : nothing;
    }
    const stays = this._stays(sel);
    if (!stays) return nothing;
    const spot = sel.sub_zone && sel.sub_zone !== "unknown" ? sel.sub_zone : null;
    const i = stays.length - 1;
    const cur = stays[i];
    // The recorder can trail the published room by a few seconds; if it has not
    // caught up, the honest answer is "just got here", not the previous stay's length.
    if (!cur || cur.unheard || cur.room !== sel.zone || (cur.spot || null) !== spot) {
      return html`<dt>Here</dt><dd>${spot || sel.zone} <span class="muted small">just arrived</span></dd>`;
    }
    let roomStart = cur.start, partial = !!cur.partial;
    for (let j = i - 1; j >= 0 && !stays[j].unheard && stays[j].room === cur.room && stays[j].floor === cur.floor; j--) {
      roomStart = stays[j].start; partial = !!stays[j].partial;
    }
    const at = (s) => new Date(s * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const long = (from, p) => html`<b>${fmtAge(cur.end - from)}${p ? "+" : ""}</b> <span class="muted small">since ${at(from)}</span>`;
    return html`<dt>Here</dt><dd>${spot || sel.zone} for ${long(cur.start, !!cur.partial)}${spot && roomStart < cur.start ? html`<br><span class="muted">in ${sel.zone} for</span> ${long(roomStart, partial)}` : nothing}</dd>`;
  }

  /** The last day as a band of stays, then the stays newest first. */
  _renderTimeline(sel) {
    const stays = this._stays(sel);
    if (!stays || !stays.length) return nothing;
    const from = stays[0].start, to = stays[stays.length - 1].end;
    const span = Math.max(1, to - from);
    const at = (s) => new Date(s * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const place = (s) => s.unheard ? "not heard" : `${s.room || "unknown"}${s.spot ? ` · ${s.spot}` : ""}`;
    const colour = (s) => s.unheard ? "transparent" : `hsl(${thingHue(s.room || "?")}, 55%, ${s.spot ? 42 : 58}%)`;
    const newest = stays.slice().reverse();
    const shown = this._timelineAll ? newest : newest.slice(0, 8);
    const now = Date.now() / 1000;
    return html`
      <details class="timeline" open>
        <summary>Timeline <span class="muted small">last ${fmtAge(span)}${stays[0].partial ? " (all that is kept)" : ""}</span></summary>
        <div class="band" role="img" aria-label=${`Where ${this._label(sel.ent)} has been, oldest on the left`}>
          ${stays.map((s) => html`<span class="seg ${s.unheard ? "unheard" : ""}" style="flex-grow: ${Math.max(0.002, (s.end - s.start) / span)}; background: ${colour(s)}" title="${at(s.start)}–${at(s.end)} · ${place(s)} · ${fmtAge(s.end - s.start)}"></span>`)}
        </div>
        <div class="band-ends muted small"><span>${at(from)}</span><span>${to >= now - 5 ? "now" : at(to)}</span></div>
        <ol class="stays">
          ${shown.map((s, n) => html`<li class=${s.unheard ? "muted" : ""}>
            <span class="swatch" style="background: ${colour(s)}"></span>
            <span class="when">${at(s.start)}–${n === 0 && s.end >= now - 5 ? "now" : at(s.end)}</span>
            <span class="what">${place(s)}${s.floor && s.floor !== sel.floor ? html` <span class="muted small">${s.floor}</span>` : nothing}</span>
            <span class="dur">${fmtAge(s.end - s.start)}${s.partial ? "+" : ""}</span>
          </li>`)}
        </ol>
        ${newest.length > 8 ? html`<button class="linkbtn" @click=${() => { this._timelineAll = !this._timelineAll; }}>${this._timelineAll ? "Show fewer" : `Show all ${newest.length}`}</button>` : nothing}
      </details>`;
  }

  _renderBlend(sel) {
    const ent = sel.ent;
    const own = this.data?.layout?.thing_fp_weights?.[ent];
    const value = this._blend != null ? this._blend : Math.round(this._blendOf(ent) * 100);
    const what = value <= 0 ? "geometric only" : value >= 100 ? "fingerprint only" : `fused, ${value}% fingerprint`;
    return html`<div class="blend" title="How this thing's position is estimated: the geometric fit from proxy distances, the fingerprint match against the proxies' references, or a blend. Applies on the next cycle.">
      <span class="muted small">Geometric</span>
      <input type="range" min="0" max="100" step="5" .value=${String(value)}
             @input=${(e) => { this._blend = Number(e.target.value); }}
             @change=${(e) => this._setBlend(ent, Number(e.target.value) / 100)}>
      <span class="muted small">Fingerprint</span>
      <span class="small">${what}${typeof own === "number" ? nothing : html` <span class="muted">(default)</span>`}</span>
      ${typeof own === "number" ? uiButton({ label: "Default", kind: "text", onClick: () => this._setBlend(ent, null), title: "Follow the tuning again" }) : nothing}
    </div>`;
  }

  /** Forget a ghost. The server decides how much goes: a thing Bermuda no
   * longer tracks (a phone after an IRK swap, a Tile after its ID rotated)
   * loses its sighting, history and settings and is gone for good; one that
   * is merely away loses the sighting and history and comes back, settings
   * intact, the next time it is heard. */
  async _forget(ent) {
    const name = this._label(ent), pn = this._pn(ent);
    if (!confirmDialog(`Forget ${name}?\n\nRemoves where ${pn.subj} ${pn.was} last seen and ${pn.poss} history. If nothing tracks ${pn.obj} any more, ${pn.poss} name, class and other settings go too and ${pn.subj} ${pn.is} gone for good; if ${pn.subj} ${pn.is} only away, ${pn.subj} ${pn.is} back - settings kept - the next time ${pn.subj} ${pn.is} heard.`)) return;
    const r = await callWS(this, this.hass, { type: "sextant/thing/forget", entity: ent });
    if (!r) return;
    toast(this, r.tracked ? `${name}: last sighting and history forgotten; ${pn.subj} will be back when heard` : `${name} forgotten${r.settings_dropped?.length ? " - settings removed too" : ""}`, 6000);
    this._select(null);
    this.dispatchEvent(new CustomEvent("layout-changed"));
  }

  _renderTruth(sel) {
    const ent = sel.ent;
    const t = this._truth && this._truth.mark?.entity === ent ? this._truth : null;
    const rows = (t?.rows || []).slice(0, 6);
    return html`<div class="truth">
      ${this._marking ? nothing
        : html`<div class="row">
            ${this._marks.length ? html`<span class="muted small">${this._marks.length} pin${this._marks.length === 1 ? "" : "s"}</span>` : nothing}</div>`}
      ${t ? html`<div class="card inner">
        <h4>Mark ${t.mark.id} <span class="muted small">${t.mark.samples} cycles re-solved · now ${Math.round((t.current_weight ?? 0) * 100)}% fingerprint</span></h4>
        ${rows.length ? html`<table class="small"><tr><th>Estimator</th><th class="num">Gain</th><th class="num">Error</th><th class="num">Room</th><th></th></tr>
          ${rows.map((r) => html`<tr><td>${r.estimator}${r.estimator === "fused" ? ` ${Math.round(r.weight * 100)}%` : ""}</td><td class="num">×${fmtNum(r.gain, 1)}</td><td class="num">${fmtLen(r.mean_m, this.hass)}</td><td class="num">${Math.round(r.room_ok * 100)}%</td>
            <td>${uiButton({ label: "Apply", kind: "text", onClick: () => this._applyRow(ent, r) })}</td></tr>`)}
        </table>
        <p class="muted small">Error is the mean distance from the pin; Room is how often the fix landed in the pin's room. One pin can overfit: pin ${this._pn(ent).obj} in another room too.</p>` : html`<p class="muted small">Nothing could be re-solved for this mark.</p>`}
        <div class="row">${uiButton({ label: "Close", kind: "text", onClick: () => { this._truth = null; } })}${uiButton({ label: "Forget pin", kind: "text", onClick: () => this._deleteMark(t.mark.id) })}</div>
      </div>` : nothing}
      ${!t && this._marks.length ? html`<details class="marks"><summary>Pins</summary>
        <ul class="plain pinlist">${this._marks.map((m) => html`<li>
          <span class="pinid">Pin ${m.id} <span class="muted">· ${m.floor}</span></span>
          <button class="forget" title="Forget pin ${m.id}" aria-label="Forget pin ${m.id}" @click=${() => this._deleteMark(m.id)}><ha-icon icon="mdi:trash-can-outline"></ha-icon></button>
          <span class="muted small pinwhen">${new Date(m.t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} · ${m.samples} cycles</span>
        </li>`)}</ul></details>` : nothing}
    </div>`;
  }

  _renderLinks(ent) {
    const row = (this._links || []).find((b) => b.device === ent);
    if (!row) return html`<div class="muted small">Loading proxies…</div>`;
    // Only proxies placed on a floor plan take part in positioning; the rest (a kiosk, a test board) are noise here.
    const placedSlugs = new Set((this.data?.layout?.floor || []).flatMap((f) => (f.receivers || []).map((r) => r.entity_id)));
    const placedAddr = new Set((this.data?.layout?.floor || []).flatMap((f) => (f.receivers || []).map((r) => String(r.address || "").toLowerCase())));
    const addrOf = (slug) => Object.entries(this.data?.scanners || {}).find(([, s]) => s.slug === slug)?.[0];
    const everything = row.receivers || [];
    const recs = everything.filter((r) => placedSlugs.has(r.scanner) || placedAddr.has(String(addrOf(r.scanner) || "").toLowerCase()));
    const dropped = everything.length - recs.length;
    return html`<details class="links">
      <summary>Heard by ${recs.length} placed ${recs.length === 1 ? "proxy" : "proxies"}${dropped ? html` <span class="muted small">(+${dropped} unplaced and ignored)</span>` : nothing}</summary>
      <table class="small"><tr><th>Proxy</th><th class="num">Distance</th></tr>
        ${recs.slice(0, 16).map((r) => html`<tr><td>${proxyName(this.data, r.scanner)}</td><td class="num">${fmtLen(r.distance, this.hass)}</td></tr>`)}
        ${recs.length > 16 ? html`<tr><td class="muted" colspan="2">and ${recs.length - 16} more</td></tr>` : nothing}
      </table>
    </details>`;
  }

  static styles = [sharedStyles, widgetStyles, css`
    /* The list floats over the map rather than taking a column from it: the
       plan runs the full width, and what is on it is read on top. The focused
       thing's detail floats in the opposite corner, out of the toolbar's way.
       Under 720px both go back to being stacked blocks (see the end). */
    :host { display: grid; grid-template-columns: 1fr; min-height: 0; position: relative; }
    .quick-actions { display: none; }
    .narrow-only { display: none; }
    .stage { position: relative; min-width: 0; }
    canvas { width: 100%; height: 100%; display: block; --sextant-map-bg: var(--card-background-color, #fff); }
    /* The map's toolbar: one compact floating panel of icon-only buttons, the
       active ones filled. The names are in each button's tooltip and aria
       label; the narrow sheet below keeps its labelled buttons. */
    .overlay { position: absolute; left: 10px; top: 10px; display: flex; flex-wrap: wrap; gap: 2px; padding: 4px; border-radius: 12px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); font-size: 12px; align-items: center; max-width: calc(100% - 20px); z-index: 2; }
    .overlay .chips { display: flex; flex-wrap: wrap; gap: 2px; }
    .overlay .qa.opt { flex-direction: row; min-width: 0; width: 34px; height: 34px; padding: 0; gap: 0; justify-content: center; border: 0; border-radius: 8px; background: transparent; position: relative; }
    .overlay .qa.opt > span { display: none; }
    .overlay .qa.opt:hover { background: var(--secondary-background-color, rgba(0,0,0,0.06)); filter: none; }
    .overlay .qa.opt.on { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
    .overlay .qa.opt .unit { position: absolute; right: 2px; bottom: 1px; font-size: 8px; line-height: 1; }
    .overlay .sep { width: 1px; align-self: stretch; margin: 4px 3px; background: var(--divider-color, rgba(0,0,0,0.12)); }
    /* Clear of the Things list, which floats over the map's right edge on a
       wide screen (as the scrubber is): at right: 10px the zoom buttons sat
       under it, out of reach. The narrow layout puts them back. */
    .zoom { position: absolute; right: 320px; bottom: 10px; display: flex; gap: 2px; padding: 4px; border-radius: 12px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); z-index: 2; }
    .zoom.lifted { bottom: 62px; }
    .wifilegend { position: absolute; right: 320px; bottom: 62px; z-index: 2; display: flex; flex-direction: column; gap: 6px; max-width: min(340px, calc(100% - 20px)); padding: 8px 10px; border-radius: 10px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.25)); font-size: 12px; }
    .wifilegend.lifted { bottom: 114px; }
    .wifilegend .ramp { display: flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; }
    .wifilegend .ramp i { flex: 1; height: 10px; min-width: 120px; border-radius: 5px; }
    .wifilegend .apkeys { display: flex; flex-wrap: wrap; gap: 4px 10px; }
    .wifilegend .apkeys span { display: inline-flex; align-items: center; gap: 4px; }
    .wifilegend .apkeys i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
    .zoom button { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 8px; background: transparent; color: var(--primary-text-color); cursor: pointer; }
    .zoom button:hover { background: var(--secondary-background-color, rgba(0,0,0,0.06)); }
    .zoom button:focus-visible, .overlay .qa.opt:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 1px; }
    .zoom ha-icon { --mdc-icon-size: 20px; }
    .overlay ha-formfield { --mdc-typography-body2-font-size: 12px; }
    .chipwrap { display: inline-flex; }
    .chipwrap > ha-formfield, .chipwrap > label.inline { border: 1px solid var(--divider-color); border-radius: 999px; padding: 0 12px 0 2px; }
    .chipwrap > label.inline { padding: 4px 12px 4px 8px; }
    .links table { margin-top: 6px; }
    .scrub { position: absolute; left: 10px; right: 320px; bottom: 10px; display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 8px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 1px 4px rgba(0,0,0,0.2)); font-size: 12px; font-variant-numeric: tabular-nums; }
    .scrub input { flex: 1; }
    .side { position: absolute; right: 10px; top: 10px; bottom: 10px; width: 300px; z-index: 3; overflow: auto; padding: 10px 12px; border-radius: 12px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.3)); }
    .detail { position: absolute; left: 10px; bottom: 10px; width: 340px; max-width: calc(100% - 340px); max-height: min(62%, calc(100% - 86px)); overflow: auto; z-index: 3; margin: 0; }
    .detail.lifted { bottom: 62px; max-height: min(62%, calc(100% - 138px)); }
    .detail h4 { display: flex; align-items: center; gap: 6px; }
    .list { list-style: none; margin: 0 0 12px; padding: 0; }
    .list li { display: grid; grid-template-columns: 30px 1fr auto; grid-template-rows: auto auto; column-gap: 10px; align-items: center; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
    .avatar { grid-row: 1 / 3; width: 30px; height: 30px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0,0,0,0.15); display: flex; align-items: center; justify-content: center; overflow: hidden; color: #fff; }
    .avatar ha-icon { --mdc-icon-size: 18px; }
    .avatar img { width: 100%; height: 100%; object-fit: cover; }
    .avatar .initials { font-size: 11px; font-weight: 700; }
    .list li:hover, .list li.selected { background: var(--secondary-background-color); }
    .list li.selected { outline: 2px solid var(--primary-color); }
    .list .name { font-weight: 600; grid-column: 2; }
    /* A badge on the disc of the thing its owner's location is read from. */
    .list .avslot { grid-row: 1 / 3; position: relative; display: inline-flex; }
    .list .avslot .viabadge.waitbadge { background: var(--warning-color, #e6a100); color: #23272e; }
    .list .avslot .viabadge.ghostbadge { background: var(--secondary-background-color, #666); color: var(--secondary-text-color); }
    .list .avslot .batterybadge { position: absolute; right: -3px; bottom: -3px; --mdc-icon-size: 12px; width: 16px; height: 16px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--warning-color, #e6a100); color: #23272e; box-shadow: 0 0 0 2px var(--card-background-color, #fff); }
    .list .avslot .batterybadge.crit { background: var(--error-color, #db4437); color: #fff; }
    dd.warn { color: var(--warning-color, #e6a100); font-weight: 600; }
    dd.crit { color: var(--error-color, #db4437); font-weight: 600; }
    .list .avslot .viabadge { position: absolute; right: -3px; top: -3px; --mdc-icon-size: 13px; width: 17px; height: 17px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); box-shadow: 0 0 0 2px var(--card-background-color, #fff); }
    /* A flex row so the icon centres on the text instead of sitting on its baseline. */
    .list .where { grid-column: 3; display: flex; align-items: center; justify-content: flex-end; gap: 4px; text-align: right; font-size: 12px; }
    /* The spot sits under its room, the way the floor sits under the name.
       The .small rule below spans columns 2 to 4; this must beat it, or the
       spot spans both columns and lands on a third row. */
    .list .small.spot { grid-column: 3; text-align: right; }
    /* The floor keeps to its own column, so the spot can sit beside it. */
    .list .small.floorline { grid-column: 2; }
    .list li.ghost { opacity: 0.7; }
    .list li.away { opacity: 0.45; }
    .list li.group.away { opacity: 0.5; }
    .list li.ghost .avatar { filter: grayscale(0.6); outline: 1px dashed var(--secondary-text-color); outline-offset: 1px; }
    .ghosticon { --mdc-icon-size: 14px; vertical-align: -2px; margin-right: 2px; }
    details.timeline { margin: 8px 0; }
    details.timeline summary { cursor: pointer; font-weight: 500; }
    .band { display: flex; height: 14px; border-radius: 4px; overflow: hidden; margin-top: 8px; background: var(--secondary-background-color); gap: 1px; }
    .band .seg { min-width: 1px; }
    .band .seg.unheard { background: repeating-linear-gradient(45deg, transparent 0 3px, var(--divider-color) 3px 5px) !important; }
    .band-ends { display: flex; justify-content: space-between; margin-top: 2px; }
    ol.stays { list-style: none; padding: 0; margin: 6px 0 0; display: grid; gap: 3px; }
    ol.stays li { display: grid; grid-template-columns: 10px auto 1fr auto; gap: 8px; align-items: center; font-size: 13px; }
    ol.stays .swatch { width: 10px; height: 10px; border-radius: 2px; }
    ol.stays .when { font-variant-numeric: tabular-nums; color: var(--secondary-text-color); white-space: nowrap; }
    ol.stays .dur { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
    .linkbtn { background: none; border: none; color: var(--primary-color); cursor: pointer; padding: 4px 0; font: inherit; }
    .list .small { grid-column: 2 / 4; }
    .dot { width: 10px; height: 10px; border-radius: 50%; grid-row: 1 / 3; }
    dl { display: grid; grid-template-columns: 90px 1fr; gap: 4px 8px; margin: 8px 0; font-size: 13px; }
    dt { color: var(--secondary-text-color); }
    dd { margin: 0; }
    .telemetry summary { cursor: pointer; font-size: 13px; }
    .telemetry dl { margin-top: 6px; }
    .blend { display: flex; align-items: center; gap: 6px; margin: 10px 0 4px; flex-wrap: wrap; }
    .blend input { flex: 1; min-width: 90px; }
    .truth { margin-top: 6px; }
    .heat { align-items: center; gap: 8px; flex-wrap: wrap; }
    .roomicon { --mdc-icon-size: 16px; flex: none; color: var(--secondary-text-color); }
    .list li .quickin { grid-column: 1 / -1; cursor: default; padding-top: 6px; }
    .list li.group { display: flex; align-items: center; gap: 6px; padding: 8px 4px 4px; margin-top: 4px; border-top: 1px solid var(--divider-color, #e0e0e0); border-radius: 0; font-weight: 500; }
    .list li.group:first-child { border-top: none; margin-top: 0; }
    .list li.group .chev { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
    /* The same disc as a thing's avatar: 30 px, white ring, hairline shadow. */
    .list li.group .gavatar { width: 30px; height: 30px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0,0,0,0.15); overflow: hidden; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; background: var(--secondary-background-color, #eee); }
    .list li.group .gavatar img { width: 100%; height: 100%; object-fit: cover; }
    .list li.group .gavatar ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
    .list li.group .gavatar { flex: none; }
    .list li.group .gtext { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
    .list li.group .gname, .list li.group .gwhere { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .list li.group .gwhere { font-weight: 400; color: var(--secondary-text-color); }
    /* One pin per row: what and where, when underneath, Forget on the right. */
    .pinlist li { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 0 10px; padding: 5px 0; border-bottom: 1px solid var(--divider-color); }
    .pinlist li:last-child { border-bottom: 0; }
    .pinlist .pinid { grid-column: 1; grid-row: 1; font-size: 13px; }
    .pinlist .pinwhen { grid-column: 1; grid-row: 2; }
    .pinlist .forget { grid-column: 2; grid-row: 1 / 3; align-self: center; display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 1px solid var(--divider-color); border-radius: 8px; background: transparent; color: var(--secondary-text-color); cursor: pointer; }
    .pinlist .forget ha-icon { --mdc-icon-size: 18px; }
    .pinlist .forget:hover { color: var(--error-color, #c62828); border-color: var(--error-color, #c62828); }
    /* Clicked on the map: floats over the plan's top-left, out of the way. */
    .proxycard { position: absolute; left: 10px; top: 64px; z-index: 3; max-width: 320px; max-height: 60%; overflow: auto; padding: 10px 12px; border-radius: 10px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.3)); }
    .proxycard h4 { margin: 0 0 6px; display: flex; align-items: center; gap: 8px; justify-content: space-between; }
    .proxycard .link { display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px; border-radius: 999px; background: var(--secondary-background-color); color: var(--secondary-text-color); font-size: 11px; font-weight: 500; white-space: nowrap; }
    .proxycard .link ha-icon { --mdc-icon-size: 14px; }
    .proxycard .link.good { background: var(--success-color, #2e7d32); color: #fff; }
    .proxycard .link.fair { background: var(--warning-color, #e6a100); color: #23272e; }
    .proxycard .link.poor { background: var(--error-color, #c62828); color: #fff; }
    .proxycard dl { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; margin: 0; font-size: 13px; }
    .proxycard dt { color: var(--secondary-text-color); }
    .proxycard dd { margin: 0; font-variant-numeric: tabular-nums; }
    .quick { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 6px; margin: 2px 0 4px; }
    .quick .qa { display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 0; padding: 6px 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border: 1px solid var(--divider-color, #ddd); border-radius: 10px; background: var(--ha-card-background, var(--card-background-color, #fff)); color: var(--primary-text-color); font: inherit; font-size: 11px; cursor: pointer; }
    .quick .qa:hover { filter: brightness(0.97); }
    .quick .qa ha-icon { --mdc-icon-size: 22px; }
    .quick .qa.on, .qa.opt.on { background: var(--primary-color, #03a9f4); border-color: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
    /* The map's switches: the same button as a thing's quick actions. */
    .qa.opt { display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 66px; padding: 5px 8px; border: 1px solid var(--divider-color, #ddd); border-radius: 10px; background: var(--ha-card-background, var(--card-background-color, #fff)); color: var(--primary-text-color); font: inherit; font-size: 11px; line-height: 1.1; white-space: nowrap; cursor: pointer; }
    .qa.opt ha-icon { --mdc-icon-size: 20px; }
    .qa.opt:hover { filter: brightness(0.97); }
    .qa.opt:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
    .optgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(84px, 1fr)); gap: 6px; }
    .quick .qa:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
    .marking .zoomto { display: flex; flex-wrap: wrap; gap: 2px 6px; margin: 4px 0; }
    .marking { background: var(--warning-color, #c77800); color: #fff; padding: 6px 8px; border-radius: 6px; font-size: 13px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .card.inner { margin-top: 8px; padding: 8px; }
    ul.plain { list-style: none; padding: 0; margin: 4px 0; font-size: 12px; }
    .opts-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.35); z-index: 9; }
    .opts-sheet { position: fixed; left: 0; right: 0; bottom: 0; z-index: 10; background: var(--card-background-color); border-radius: 14px 14px 0 0; padding: 14px 16px max(14px, env(safe-area-inset-bottom)); box-shadow: 0 -2px 12px rgba(0,0,0,0.25); display: flex; flex-direction: column; gap: 10px; max-height: 70vh; overflow: auto; }
    .opts-sheet .chips.optgrid { flex-direction: row; align-items: stretch; }
    .opts-sheet .chipwrap { justify-content: space-between; }
    .opts-sheet .chipwrap > ha-formfield, .opts-sheet .chipwrap > label.inline { width: 100%; justify-content: space-between; }
    /* Small buttons a phone user reaches for right away: jump straight to
       the page that does the thing, instead of hunting through the mode
       tabs. Calibration and adding a thing are admin actions - offered
       only when this user could reach those pages at all. */
    .quick-actions button { display: flex; align-items: center; gap: 6px; }
    .side h3 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .maptoggle { margin-left: auto; }
    /* Quick pin (phones; see _startPin). The list and done steps are sheets
       over the whole screen; the map step is the stage itself gone
       full-screen, with the chips, the ring and one button laid over it. */
    .pinfab { position: fixed; right: 16px; bottom: calc(64px + env(safe-area-inset-bottom, 0px)); z-index: 6; height: 52px; padding: 0 20px 0 16px; border: 0; border-radius: 999px; background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); font: inherit; font-weight: 600; font-size: 15px; align-items: center; gap: 6px; box-shadow: 0 6px 20px rgba(0,0,0,0.35); cursor: pointer; }
    .pinfab ha-icon { --mdc-icon-size: 22px; }
    .pinsheet { position: fixed; inset: 0; z-index: 8; display: flex; flex-direction: column; background: var(--primary-background-color, #fafafa); color: var(--primary-text-color); }
    .pinhead { display: flex; align-items: center; gap: 12px; padding: calc(12px + env(safe-area-inset-top, 0px)) 16px 8px; }
    .pinhead h3, .pinbar h3 { margin: 0; font-size: 18px; font-weight: 600; line-height: 1.2; text-transform: none; letter-spacing: 0; color: var(--primary-text-color); }
    .iconbtn.round { width: 40px; height: 40px; background: var(--secondary-background-color, rgba(0,0,0,0.06)); color: var(--primary-text-color); display: inline-flex; align-items: center; justify-content: center; flex: none; }
    .pincheck { width: 40px; height: 40px; border-radius: 50%; background: var(--success-color, #43a047); color: #fff; display: inline-flex; align-items: center; justify-content: center; flex: none; }
    .pinbody { flex: 1 1 auto; min-height: 0; overflow: auto; -webkit-overflow-scrolling: touch; }
    .pinsection { padding: 14px 16px 4px; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
    .pinsection.accent { color: var(--warning-color, #c77800); }
    .pinbody ul.plain { margin: 0; padding: 0; }
    .pinrow { width: 100%; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 12px; min-height: 60px; padding: 8px 16px; border: 0; border-bottom: 1px solid var(--divider-color, #e0e0e0); background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
    .pinrow.big { min-height: 68px; background: var(--card-background-color); }
    .pinrow.ghost { opacity: 0.55; }
    .pinrow:active { background: var(--secondary-background-color, rgba(0,0,0,0.06)); }
    .pinrow .avatar { grid-row: auto; }
    .pinrow .pintext { display: flex; flex-direction: column; min-width: 0; }
    .pinrow .pintext .name { font-weight: 500; font-size: 16px; }
    .pinrow .pintext > * { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .pinrow ha-icon { color: var(--secondary-text-color); }
    .pinbody .pad { padding: 0 16px; }
    .pintable { width: calc(100% - 32px); margin: 0 16px; border-collapse: collapse; }
    .pintable th, .pintable td { padding: 8px 6px; border-bottom: 1px solid var(--divider-color, #e0e0e0); font-variant-numeric: tabular-nums; }
    .pintable th { text-align: left; font-weight: 500; color: var(--secondary-text-color); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
    .pintable .num { text-align: right; }
    .pintable tr.best td { background: color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); font-weight: 600; }
    .pinbar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: var(--card-background-color); }
    .pintop { position: absolute; left: 0; right: 0; top: 0; z-index: 2; display: flex; flex-direction: column; background: var(--card-background-color); box-shadow: 0 1px 0 var(--divider-color, #e0e0e0); padding-bottom: 4px; }
    .pinbar.top { padding-top: calc(10px + env(safe-area-inset-top, 0px)); padding-bottom: 6px; }
    .pinbar.bottom { position: absolute; left: 0; right: 0; bottom: 0; z-index: 2; padding-bottom: calc(14px + env(safe-area-inset-bottom, 0px)); box-shadow: 0 -1px 0 var(--divider-color, #e0e0e0); }
    .pinsheet .pinbar.bottom { position: static; }
    .pinbar.stack { flex-direction: column; align-items: stretch; gap: 10px; }
    .pinpair { display: flex; gap: 10px; }
    .pinplace { flex: 1 1 auto; display: inline-flex; align-items: center; justify-content: center; gap: 8px; height: 54px; border: 0; border-radius: 14px; background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); font: inherit; font-size: 17px; font-weight: 600; cursor: pointer; }
    .pinplace[disabled] { opacity: 0.6; cursor: default; }
    .pinplace ha-icon { --mdc-icon-size: 22px; }
    .pinsecondary { flex: 1 1 0; height: 46px; border: 1px solid var(--divider-color, #e0e0e0); border-radius: 14px; background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-weight: 500; cursor: pointer; }
    .pinchips { display: flex; gap: 6px; padding: 4px 12px; overflow-x: auto; scrollbar-width: none; }
    .pinchips::-webkit-scrollbar { display: none; }
    .pinchip { flex: none; padding: 7px 12px; border-radius: 999px; border: 1px solid var(--divider-color, #e0e0e0); background: var(--secondary-background-color, rgba(0,0,0,0.04)); color: var(--primary-text-color); font: inherit; font-size: 13px; font-weight: 500; white-space: nowrap; cursor: pointer; }
    .pinchip.spot { font-weight: 400; }
    .pinchip.on { background: var(--primary-color, #03a9f4); border-color: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
    .pinring { position: absolute; left: 50%; top: 50%; width: 56px; height: 56px; margin: -28px 0 0 -28px; border-radius: 50%; border: 2px solid var(--warning-color, #ffb648); box-shadow: 0 0 0 1px rgba(0,0,0,0.5), inset 0 0 0 1px rgba(0,0,0,0.5); pointer-events: none; z-index: 1; }
    .pinring span { position: absolute; background: var(--warning-color, #ffb648); box-shadow: 0 0 0 1px rgba(0,0,0,0.4); }
    .pinring .n, .pinring .s { left: 50%; width: 2px; height: 16px; margin-left: -1px; }
    .pinring .n { top: -26px; } .pinring .s { bottom: -26px; }
    .pinring .w, .pinring .e { top: 50%; height: 2px; width: 16px; margin-top: -1px; }
    .pinring .w { left: -26px; } .pinring .e { right: -26px; }
    .pinring .dot { left: 50%; top: 50%; width: 6px; height: 6px; margin: -3px 0 0 -3px; border-radius: 50%; }
    .pinhint, .pinunder { position: absolute; z-index: 2; padding: 6px 12px; border-radius: 999px; background: var(--card-background-color); color: var(--secondary-text-color); font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,0.25); pointer-events: none; }
    .pinhint { left: 50%; transform: translateX(-50%); top: calc(50% - 76px); white-space: nowrap; }
    .pinunder { left: 12px; bottom: calc(92px + env(safe-area-inset-bottom, 0px)); color: var(--primary-text-color); font-weight: 500; }
    /* The map step: the stage is the screen. Its own toolbar, zoom cluster
       and scrubber step aside; the rest of the page sits under it. */
    :host(.pinning) .stage, :host(.pinning) .stage.collapsed { display: block; position: fixed; inset: 0; z-index: 8; flex: none; background: var(--card-background-color); }
    :host(.pinning) .overlay, :host(.pinning) .zoom, :host(.pinning) .scrub, :host(.pinning) .opts-sheet, :host(.pinning) .opts-backdrop { display: none; }

    @media (max-width: 720px) {
      /* Flex, not grid: a collapsed .stage (display:none) then simply takes
         no space, and the list gets the room back - a grid track sized for
         it would stay reserved even once nothing is in it. The list comes
         first ("where is everything", read as text) and the map - fixed at
         about half the screen so it is worth looking at once open - sits
         below it, above the selected thing's own detail card. */
      :host { display: flex; flex-direction: column; }
      .quick-actions { order: 0; display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 10px; background: var(--card-background-color); border-bottom: 1px solid var(--divider-color); }
      .side { position: static; order: 1; flex: 1 1 auto; width: auto; min-height: 0; overflow: auto; border-left: 0; border-top: 1px solid var(--divider-color); max-height: none; border-radius: 0; box-shadow: none; padding: 12px; }
      /* The card takes what it needs unless the grip has set a height; then
         it is that tall and scrolls inside, and the list gets the rest. */
      .detail, .detail.lifted { position: static; order: 3; width: auto; max-width: none; max-height: none; margin: 0 10px 10px; flex: 0 0 auto; }
      :host([style*="--sextant-detail-h"]) .detail, :host([style*="--sextant-detail-h"]) .detail.lifted { flex: 0 0 var(--sextant-detail-h); height: var(--sextant-detail-h); overflow: auto; }
      .detail .grip { display: flex; justify-content: center; align-items: center; height: 22px; margin: -12px -14px 0; touch-action: none; cursor: ns-resize; position: sticky; top: -12px; z-index: 1; background: var(--card-background-color); }
      .detail .grip span { width: 44px; height: 5px; border-radius: 3px; background: var(--divider-color, #c0c0c0); }
      .detail .grip:active span, .detail .grip:focus-visible span { background: var(--primary-color, #03a9f4); }
      .detail .grip:focus-visible { outline: none; }
      .scrub, .zoom, .wifilegend { right: 10px; }
      /* Things, and with it Hide map, stays reachable however far the list
         is scrolled - it used to scroll away and leave no way to close a map
         taking half the screen. */
      .side h3 { position: sticky; top: 0; z-index: 2; margin: 0; padding: 8px 0; background: var(--card-background-color); }
      .stage { order: 2; flex: 0 0 48vh; }
      .stage.collapsed { display: none; }
      .wide-only { display: none; }
      .narrow-only { display: flex; }
    }
  `];
}

if (!customElements.get("sextant-live")) customElements.define("sextant-live", SextantLive);
if (!customElements.get("sextant-panel")) customElements.define("sextant-panel", SextantPanel);
