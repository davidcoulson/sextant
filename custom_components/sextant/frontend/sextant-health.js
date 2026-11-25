/**
 * Proxies, Calibration and Tuning modes (one element, three sections).
 *
 * section="proxies":     every placed proxy grouped by floor and room, with
 *                        a health count per group, plus the self-test.
 * section="calibration": proxy calibration runs and their corrections.
 * section="tuning":      the stability KPI with baselines, live tuning, and
 *                        history retention.
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { pointInPolygon } from "./sextant-map.js";
import { sharedStyles, widgetStyles, fmtAge, fmtNum, toast, callWS, confirmAsync, uiField, uiSelect, uiSwitch, uiButton, sortFloors, thingName, proxyName, fmtLen, isImperial } from "./sextant-ui.js";

// A far move is a room change to a room on the same floor whose outline is
// more than 2.5 m from the previous room's. Walked, it passes through
// somewhere in between; one the plan never saw in between is a position
// that jumped. Each pet in the house this was built on makes about ten a
// day; a rise after a change is what matters, not the level.
const FAR_MOVES_HELP = "Moves per day to a room on the same floor that is not a neighbour (outlines more than 2.5 m apart). Walked moves pass through a room in between; these did not, so they are the ones to watch.";
const QUIET_SECS = 120;   // online, but nothing heard for this long: "quiet"

/** Whether a tuning key matches the filter text (key name, label or help, case-insensitive). */
function tuningMatches(key, label, help, q) {
  const needle = String(q || "").trim().toLowerCase();
  return !needle || `${key} ${label} ${help}`.toLowerCase().includes(needle);
}
/** True when a tuning value differs from its default (an unset value is the default). */
function tuningChanged(value, def) {
  if (value === "" || value == null) return false;
  return typeof def === "number" ? Number(value) !== def : value !== def;
}
/** Help line for a tuning key: the meaning, an imperial equivalent for metre keys, then the default. */
function tuningHelpLine(key, help, def, imperial) {
  const ft = (m) => `${Math.round(m * 3.28084 * 10) / 10} ft`;
  const metric = key.endsWith("_m") && typeof def === "number";
  const d = metric && imperial ? `${def} m (${ft(def)})` : String(def);
  return `${help ? help + " " : ""}Default ${d}.`;
}

/** Plain labels for the tuning keys, with a one-line meaning; the key itself is shown under the field. */
// The settings the room election reads (replay.ROOM_KEYS): the ones a replay can try.
const REPLAY_KEYS = ["zone_switch_secs", "zone_switch_margin", "zone_prob_smoothing", "stationary_speed", "stationary_secs", "zone_lock_warmup_secs",
  "zone_unlock_margin", "zone_unlock_secs", "far_move_margin", "far_move_secs", "zone_anchor_inset_m", "habit_margin_gain"];
const TUNING_LABELS = {
  position_estimator: ["Position estimator", "geometric = trilateration alone; fingerprint = proxy references alone; fused = a blend of both"],
  fingerprint_weight: ["Fingerprint share of the fix", "0 is the trilateration alone, 1 the fingerprint alone"],
  fingerprint_floor_weight: ["Fingerprint share of floor confidence", "how much the fingerprint match counts in the floor election"],
  fingerprint_k: ["References averaged per fix", "the best-matching proxies whose positions are averaged"],
  fingerprint_missing_m: ["Not heard counts as (m)", "a proxy that does not hear the thing is treated as this far away"],
  fingerprint_ref_gain: ["Reference gain", "probe beacons hotter (<1) or cooler (>1) than the things"],
  fingerprint_auto_gain: ["Learn reference gain from things", "walk the gain in from every match, published per fix as fp.gain"],
  range_auto_scale: ["Apply learned range scale", "multiply each thing's ranges by the scale learned from its own fits, published per fix as range_scale"],
  fingerprint_marks: ["Location pins as references", "each pin from the Live page is also a fingerprint reference at that point"],
  distance_estimator: ["Distance estimator", "bermuda = Bermuda's smoothed distance; median = the median of the recent raw RSSI samples"],
  median_window_secs: ["Median window (s)", "only samples newer than this feed the median"],
  stale_interval_factor: ["Stale after (× heard gap)", "a reading is dropped this many times the gap its proxy usually hears the thing at (10 s floor, reading_max_age cap); 0 uses reading_max_age alone"],
  median_min_samples: ["Median minimum samples", "fewer than this falls back to Bermuda's distance"],
  solver_max_receivers: ["Nearest proxies per solve", "0 uses every proxy that hears the thing"],
  solver_max_range: ["Drop readings beyond (m)", "once three proxies remain; 0 never drops"],
  solver_near_always: ["Always use proxies within (m)", "proxies this close count whatever the cap"],
  zone_hysteresis: ["Room hysteresis", "off publishes the instantaneous room every cycle"],
  zone_prob_smoothing: ["Room share smoothing", "weight on the previous cycle's room shares"],
  zone_switch_margin: ["Room switch margin", "the lead a challenger room needs"],
  zone_switch_secs: ["Room switch dwell (s)", "held that long before the room changes"],
  far_move_margin: ["Far move margin", "the lead a room that is not next door needs (the larger of this and the switch margin)"],
  far_move_secs: ["Far move dwell (s)", "held that long before jumping to a room that is not next door; 0 = no longer than any move"],
  stationary_speed: ["Stationary below (m/s)", "slower than this counts as still"],
  stationary_secs: ["Stationary after (s)", "still this long locks the room"],
  outside_margin_m: ["Outside beyond (m)", "a fix this far beyond every room reads Outside; 0 turns it off"],
  outside_secs: ["Outside after (s)", "for this long before it reads Outside, and back inside"],
  outside_faint_prox: ["Dog outside: heard by at most", "a dog heard by no more than this many proxies, with the nearest at least the distance below away, reads Outside even when its fix lands in a room; 0 turns it off"],
  outside_faint_m: ["Dog outside: nearest at least (m)", "the nearest proxy this far or farther, with few hearing it, is a dog in the garden"],
  outside_near_m: ["Dog inside: nearest within (m)", "a proxy this close means the dog is back in the house"],
  zone_unlock_margin: ["Unlock outside room by (m)", "the fix must sit this far outside the locked room"],
  zone_unlock_secs: ["Unlock after (s)", "for this long before the lock releases"],
  subzone_switch_secs: ["Spot switch dwell (s)", "a spot change waits this long"],
  subzone_enter_prob: ["Spot entry share", "the smoothed share of the fix inside a spot needed to enter it"],
  subzone_unlock_margin: ["Leave spot outside by (m)", "the fix must sit this far outside a spot before leaving it"],
  anchor_max_m: ["Anchor within (m)", "one proxy reading closer than this can anchor the thing; 0 turns anchoring off"],
  anchor_ratio: ["Others at least × farther", "every other proxy must read at least this many times farther"],
  anchor_secs: ["Anchor after (s)", "the condition must hold this long"],
  anchor_release_m: ["Release beyond (m)", "the anchor lets go once the reading opens past this"],
  zone_anchor_inset_m: ["Anchor moves the room (m)", "an anchored thing's room is its proxy's room at once when the proxy is this far inside it; 0 turns it off"],
  floor_switch_secs: ["Floor switch dwell (s)", "a challenger floor must lead this long"],
  floor_switch_margin: ["Floor switch margin", "the lead a challenger floor needs before that dwell starts; 0.10 holds a still thing between two near-tied floors"],
  floor_tenure_bonus: ["Tenure bonus", "extra margin an incumbent floor earns at full tenure"],
  floor_tenure_full_secs: ["Full tenure after (s)", "tenure is counted up to this"],
  floor_proximity_weight: ["Proximity weight", "how much nearest-proxy proximity scales a floor's score; 0 judges the fit alone"],
  wifi_floor_weight: ["Wi-Fi floor hint", "how much the access point a person's phone or watch is on sways their floor: a floor it never means scores this much less; 0 = off"],
  floor_proximity_k: ["Proxies averaged for proximity", "the k nearest proxies whose distances are averaged"],
  floor_proximity_blend: ["Proximity blend", "gated = fit × ((1 − w) + w × proximity), a poor fit caps the floor; geometric = fit^(1 − w) × proximity^w, the nearest proxies can carry a floor whose fit is poor (a fix over a void)"],
  subzone_lock_release_m: ["Spot lock release (m)", "how far a still thing's fix must leave its spot before the room lock stops holding it there"],
  away_after_secs: ["Away after (s)", "unheard this long, the Live list stops waiting for a thing and calls it away; between ghost and this it is shown where it was last seen"],
  restore_state_secs: ["Resume after a restart within (s)", "a restart shorter than this resumes the elections; longer starts cold (raise before a host reboot)"],
  gps_stale_secs: ["GPS source stale after (s)", "a person's GPS tracker that has not reported for this long is passed over for the next one"],
  exit_door_secs: ["Outside door opened within (s)", "where a room's outside door has a contact sensor (Edit page), someone quiet there has gone out only if an outside door was open within this long of when they were last heard; 0 = doors not asked"],
  watch_still_secs: ["Watch left behind after (s)", "a watch that had been still this long when its owner's phone went to another room was left behind, and the phone places them; 0 = off"],
  exit_quiet_secs: ["Gone out after (s)", "a person last heard in a room with an outside door reads Outside once quiet this long; 0 = off"],
  gps_leave_m: ["GPS ends the hold beyond (m)", "a person gone quiet is held in their last room until Away after runs out, unless a GPS fix made since the last sighting puts them outside the home zone and at least this far from home; 0 = off"],
  robot_poll_secs: ["Robot position every (s)", "how often a robot vacuum that is out is asked where it is; each ask is a map parse in the Roborock integration"],
  mmwave_fusion: ["Place things on mmWave targets", "a thing whose Bluetooth fix is near a radar target is placed on the target"],
  mmwave_auto_pins: ["Pins from mmWave", "one still target and one still thing make a location pin (at most one per thing per half hour)"],
  mmwave_pair_m: ["Claim a target within (m)", "how near a thing's Bluetooth fix must be to an mmWave target to be placed on it"],
  mmwave_merge_m: ["One person within (m)", "two mmWave sensors' targets this close are one person seen by both, counted and claimed once"],
  mmwave_tick_s: ["Read mmWave every (s)", "how often the radars are read and their tracks followed, on their own clock between cycles"],
  mmwave_verify_s: ["Count a target after (s)", "a target is drawn at once but counted, and claimed for a room, only once seen this long: a reflection flickers and is gone"],
  mmwave_hold_s: ["Keep a lost target for (s)", "where a radar loses someone they stay, counted and their room occupied, this long; a room's own 'Stays occupied for' on the Edit page overrides it"],
  mmwave_rooms: ["Rooms from mmWave", "a room's occupancy sensor is on while a radar track is in it, device or no device"],
  election_log_hours: ["Election log (hours)", "keep every floor election on disk for this long (config/sextant_election_log, ~6 MB an hour for twenty things, gzipped to about a sixth once the hour is over) for tools/replay_floors.py; 0 = off"],
  stale_after_secs: ["Ghost after (s)", "a thing unheard this long is drawn faded on Live, with how long ago it was heard"],
  spot_proxy_near_m: ["Spot proxy: full within (m)", "a spot's own proxy hearing a thing this close counts fully as the thing being on the spot"],
  spot_proxy_far_m: ["Spot proxy: nothing from (m)", "from this far the spot's proxy says nothing; between the two it fades"],
  spot_proxy_ratio: ["Spot proxy: clearly nearest ×", "every other proxy must read this many times farther for full weight (none within 1.25×)"],
  zone_lock_warmup_secs: ["Lock warm-up (s)", "no stationary lock until a thing has been tracked this long since a start or a floor change"],
  fingerprint_marks_scope: ["Pins guide", "whose location pins place a thing: own = only its own; class = also those of things of its class (the cats share one another's); all = everyone's"],
  history_hours: ["History kept (hours)", "how far back the history scrubber, the timeline and Activity reach (1 to 168)"],
  calibration_target: ["Calibration writes to", "sextant = a per-proxy factor in the layout; bermuda = per-scanner RSSI offsets in Bermuda"],
  correction_close_fade: ["Fade stretch up close", "a proxy calibration stretches (factor above 1) pushes a thing lying right beside it away; fade that stretch out at short range"],
  correction_fade_near_m: ["No stretch within (m)", "a reading this close gets none of its proxy's stretch"],
  correction_fade_far_m: ["Full stretch from (m)", "from this far out the proxy's stretch applies in full; between the two it fades in"],
};

// The self-test and the advice take seconds to compute and are worth keeping:
// switching to another page tears this element down, so the last result is
// stored in the browser and restored when the page comes back (for a day),
// and flagged as stale with a Refresh prompt once it is over an hour old.
const REMEMBER_MS = 24 * 60 * 60 * 1000;
const STALE_MS = 60 * 60 * 1000;
function remember(key, value) {
  try { localStorage.setItem(`sextant.${key}`, JSON.stringify({ at: Date.now(), value })); } catch { /* private mode */ }
}
function recall(key) {
  try {
    const raw = localStorage.getItem(`sextant.${key}`);
    if (!raw) return null;
    const { at, value } = JSON.parse(raw);
    return Date.now() - at <= REMEMBER_MS ? { ...value, at } : null;
  } catch { return null; }
}
function stale(result) {
  return !!(result && result.at && Date.now() - result.at > STALE_MS);
}

class SextantHealth extends LitElement {
  static properties = {
    expert: { type: Boolean },
    hass: { attribute: false },
    data: { attribute: false },
    positions: { attribute: false },
    floor: { type: String },
    section: { type: String },
    _receivers: { state: true },
    _tfilter: { state: true },
    _cal: { state: true },
    _selftest: { state: true },
    _report: { state: true },
    _logUse: { state: true },
    _advice: { state: true },
    _kpi: { state: true },
    _accuracy: { state: true },
    _pinHealth: { state: true },
    _kpiHours: { state: true },
    _replay: { state: true },
    _replayKey: { state: true },
    _replayValue: { state: true },
    _replayHours: { state: true },
    _baselines: { state: true },
    _baseline: { state: true },
    _baselineName: { state: true },
    _linking: { state: true },
    _busy: { state: true },
    _tuning: { state: true },
    _calDuration: { state: true },
    _open: { state: true },
  };

  constructor() {
    super();
    this.section = "proxies";
    this._receivers = null;
    this._cal = null;
    this._selftest = recall("selftest");
    this._advice = recall("advice");
    this._kpi = null;
    this._kpiHours = 12;
    this._replay = null;
    this._replayKey = "zone_switch_secs";
    this._replayValue = "";
    this._replayHours = 6;
    this._baselines = [];
    this._baseline = "";
    this._baselineName = "";
    this._linking = null;
    this._busy = null;
    this._tuning = {};
    this._tfilter = "";
    this._calDuration = 600;
    this._open = new Set();   // expanded floor/room groups
  }

  connectedCallback() {
    super.connectedCallback();
    this._refresh();
    this._timer = setInterval(() => { if (document.visibilityState === "visible") this._poll(); }, 10000);
    this._onVisible = () => { if (document.visibilityState === "visible") this._poll(); };
    document.addEventListener("visibilitychange", this._onVisible);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this._timer);
    document.removeEventListener("visibilitychange", this._onVisible);
  }

  willUpdate(changed) {
    // The signal map is admin only: a user who loses admin while the page is
    // open loses the copy already shown too.
    if (changed.has("hass") && !this._isAdmin()) this._wifiHeat = null;
  }

  updated(changed) {
    if (changed.has("data") && this.data) this._tuning = { ...(this.data.layout?.tuning || {}) };
    if (this.section === "tuning" && this._logUse === undefined && this.hass && this._isAdmin()) {
      this._logUse = null;
      this.hass.callWS({ type: "sextant/election_log/usage" }).then((r) => { this._logUse = r; }).catch(() => {});
    }
  }

  async _refresh() {
    if (!this.hass) return;
    const [rx, cal] = await Promise.all([
      this.hass.callWS({ type: "sextant/receivers" }).catch(() => null),
      this.hass.callWS({ type: "sextant/calibration/status" }).catch(() => null),
    ]);
    this._receivers = rx;
    this._cal = cal;
    this._loadBaselines();
    this._loadWifiHeat();
  }

  async _loadWifiHeat() {
    if (!this.hass || !this._isAdmin()) { this._wifiHeat = null; return; }
    const r = await this.hass.callWS({ type: "sextant/wifi/heat", field: true }).catch(() => null);
    // Asked again after the answer: admin may have gone while it was on its way.
    this._wifiHeat = this._isAdmin() ? r : null;
    this.requestUpdate();
  }

  async _clearWifiHeat() {
    if (!(await confirmAsync("Start the Wi-Fi signal map over? Every sample so far is dropped. Do this after moving or replacing access points.", { ok: "Start over", danger: true }))) return;
    const r = await callWS(this, this.hass, { type: "sextant/wifi/heat/clear" });
    if (!r) return;   // callWS has said what went wrong; the samples are still there
    toast(this, "Wi-Fi signal map cleared");
    this._loadWifiHeat();
  }

  async _poll() {
    if (!this.hass) return;
    const cal = await this.hass.callWS({ type: "sextant/calibration/status" }).catch(() => null);
    if (cal) this._cal = cal;
    if (this._cal?.state === "sampling" || this._cal?.mode === "auto") return;
    const rx = await this.hass.callWS({ type: "sextant/receivers" }).catch(() => null);
    if (rx) this._receivers = rx;
  }

  /** The floor calibration acts on: the one picked in the header. */
  get _calFloor() { return this.floor || this._cal?.floor || this.data?.layout?.floor?.[0]?.name || null; }

  async _calAction(action, extra = {}) {
    this._busy = action;
    const r = await callWS(this, this.hass, { type: "sextant/calibration/action", action, ...extra });
    this._busy = null;
    if (r) {
      this._cal = r;
      if (action === "apply") { toast(this, `Applied corrections to ${r.applied} proxy(ies)`); this.dispatchEvent(new CustomEvent("layout-changed")); }
      else if (action === "reset") { toast(this, `Reset ${r.reset} proxy(ies)`); this.dispatchEvent(new CustomEvent("layout-changed")); }
    }
  }

  async _runSelftest() {
    this._busy = "selftest";
    const r = await callWS(this, this.hass, { type: "sextant/selftest" });
    this._busy = null;
    if (r) { this._selftest = { ...r, at: Date.now() }; remember("selftest", r); }
  }

  async _runReport() {
    this._busy = "report";
    const r = await callWS(this, this.hass, { type: "sextant/receiver_report", hours: 6 });
    this._busy = null;
    if (r) this._report = r;
  }

  /** Move a proxy the self-test calls misplaced to where the others hear it.
   * Reads the stored plan fresh, so nothing saved since this page loaded is
   * undone; the server keeps the plan it replaces under Edit's History. */
  async _moveProxy(v) {
    const name = proxyName(this.data, v.entity);
    if (!(await confirmAsync(`Move ${name} ${fmtLen(v.error_m, this.hass, 1)} on the plan, to where the other proxies hear it${v.est_room ? ` (${v.est_room})` : ""}?\n\nDo this only if it really is there: a proxy behind a thick wall or inside a metal box can read far away while drawn in the right place. The plan as it is now is kept under History on the Edit page.`, { ok: "Move it" }))) return;
    this._busy = "selftest";
    const d = await callWS(this, this.hass, { type: "sextant/layout/get" });
    const rec = (d?.layout?.floor || []).find((f) => f.name === v.floor)?.receivers?.find((r) => String(r.entity_id) === v.entity);
    // Moved since the test ran: its answer is about the old place.
    const stale = rec && (Math.abs(rec.cords?.x - v.known[0]) > 0.06 || Math.abs(rec.cords?.y - v.known[1]) > 0.06);
    const saved = rec && !stale && (rec.cords = { ...rec.cords, x: v.est[0], y: v.est[1] })
      && await callWS(this, this.hass, { type: "sextant/layout/save", layout: d.layout });
    this._busy = null;
    if (!saved) {
      if (d && !rec) toast(this, `${name} is no longer on ${v.floor}`);
      else if (stale) { toast(this, `${name} was moved since this test; running it again`); this._runSelftest(); }
      return;
    }
    toast(this, `${name} moved`);
    this.dispatchEvent(new CustomEvent("layout-changed"));
    this._runSelftest();
  }

  async _runKpi() {
    this._busy = "kpi";
    const msg = { type: "sextant/kpi", hours: this._kpiHours };
    if (this._baseline) msg.baseline = this._baseline;
    const r = await callWS(this, this.hass, msg);
    this._busy = null;
    if (r) this._kpi = r;
  }

  async _runReplay() {
    const value = Number(this._replayValue);
    if (this._replayValue === "" || !Number.isFinite(value)) { toast(this, "Enter a value to try"); return; }
    this._busy = "replay";
    const r = await callWS(this, this.hass, { type: "sextant/replay", tuning: { [this._replayKey]: value }, hours: this._replayHours });
    this._busy = null;
    if (r) this._replay = { ...r, key: this._replayKey, value };
  }

  async _loadBaselines() {
    const r = await this.hass.callWS({ type: "sextant/kpi/baselines" }).catch(() => null);
    if (r) {
      this._baselines = r.baselines || [];
      if (this._baseline && !this._baselines.some((b) => b.name === this._baseline)) this._baseline = "";
    }
  }

  async _saveBaseline() {
    const name = (this._baselineName || "").trim();
    if (!name) return;
    this._busy = "baseline";
    const r = await callWS(this, this.hass, { type: "sextant/kpi/baseline/save", name, hours: this._kpiHours });
    this._busy = null;
    if (r) {
      toast(this, `Saved baseline "${r.name}" (${r.things} things, ${this._kpiHours} h)`);
      this._baselineName = "";
      await this._loadBaselines();
      this._baseline = r.name;
    }
  }

  async _deleteBaseline(name) {
    if (!name || !(await confirmAsync(`Delete the KPI baseline "${name}"?`, { ok: "Delete", danger: true }))) return;
    const r = await callWS(this, this.hass, { type: "sextant/kpi/baseline/delete", name });
    if (r) { toast(this, `Deleted baseline "${name}"`); this._baseline = ""; if (this._kpi) this._kpi = { ...this._kpi, baseline: undefined, deltas: undefined }; await this._loadBaselines(); }
  }

  async _loadLinking() {
    const r = await callWS(this, this.hass, { type: "sextant/scanner_linking" });
    if (r) this._linking = r;
  }

  async _saveTuning() {
    const spec = this.data?.tuning_spec || {};
    const settings = {};
    for (const [k, v] of Object.entries(this._tuning)) {
      const s = spec[k];
      if (!tuningChanged(v, s?.default)) continue;   // defaults are not stored as overrides
      settings[k] = s?.type === "bool" ? !!v : s?.type === "str" ? String(v) : Number(v);
    }
    const r = await callWS(this, this.hass, { type: "sextant/tuning/set", settings, reset: true });
    if (r) { toast(this, "Tuning applied live"); this._tuning = { ...r.tuning }; this.dispatchEvent(new CustomEvent("layout-changed")); }
  }

  async _resetTuning() {
    if (!(await confirmAsync("Restore every tuning value to its default?", { ok: "Restore defaults", danger: true }))) return;
    const r = await callWS(this, this.hass, { type: "sextant/tuning/set", reset: true });
    if (r) { toast(this, "Defaults restored"); this._tuning = {}; this.dispatchEvent(new CustomEvent("layout-changed")); }
  }

  render() {
    switch (this.section) {
      case "calibration":
        return html`<div class="page"><div class="cols">${this._renderCalibration()}</div></div>`;
      case "tuning":
        return html`<div class="page"><div class="cols">${this._renderKpi()}${this._renderTuning()}
          <details class="fold"><summary>Experiments and history: accuracy against pins, try a setting, forget history</summary><div class="cols">${this._renderAccuracy()}${this._renderReplay()}${this._renderHistory()}</div></details></div></div>`;
      case "advice":
        return html`<div class="page"><div class="cols">${this._renderAdvice()}${this._isAdmin() ? this._renderPinHealth() : nothing}</div></div>`;
      default:
        return html`<div class="page"><div class="cols">${this._renderReceivers()}
          <details class="fold" ?hidden=${!this.expert}><summary>Diagnostics: proxy self-test, proxies against real fixes, Wi-Fi signal by room</summary><div class="cols">${this._renderSelftest()}${this._renderReport()}${this._renderWifiRooms()}</div></details></div></div>`;
    }
  }

  // --- Proxies -------------------------------------------------------------------

  /** A proxy's status: "offline", "unmatched", "quiet", "behind" or "ok". */
  _status(r) {
    if (!r.matched) return "unmatched";
    if (!r.online) return "offline";
    const age = r.last_seen_age ?? r.age;
    if (age != null && age > QUIET_SECS) return "quiet";
    if (r.firmware_behind) return "behind";
    return "ok";
  }

  /** The room (non-no-go zone) a proxy's placement falls in, from the layout. */
  _roomOf(r) {
    const floor = (this.data?.layout?.floor || []).find((f) => f.name === r.floor);
    const placed = (floor?.receivers || []).find((x) => x.entity_id === r.slug || (r.address && x.address === r.address));
    if (!floor || !placed?.cords) return null;
    const hit = (floor.zones || []).find((z) => !z.no_go && (z.cords || []).length >= 3 && pointInPolygon({ x: placed.cords.x, y: placed.cords.y }, z.cords));
    return hit?.entity_id || null;
  }

  _toggle(key) {
    const s = new Set(this._open);
    s.has(key) ? s.delete(key) : s.add(key);
    this._open = s;
  }

  _counts(rows) {
    const c = { ok: 0, quiet: 0, offline: 0, unmatched: 0, behind: 0 };
    for (const r of rows) c[this._status(r)]++;
    return c;
  }

  _countPills(c) {
    return html`<span class="counts">
      ${c.ok ? html`<span class="pill ok" title="online and heard recently">${c.ok}</span>` : nothing}
      ${c.quiet ? html`<span class="pill quiet" title="online but nothing heard for ${QUIET_SECS} s">${c.quiet}</span>` : nothing}
      ${c.offline ? html`<span class="pill bad" title="offline">${c.offline}</span>` : nothing}
      ${c.unmatched ? html`<span class="pill warn" title="placed but Bermuda has no scanner by that name">${c.unmatched}</span>` : nothing}
      ${c.behind ? html`<span class="pill warn" title="older firmware than most proxies: an update failed or never ran">${c.behind} behind</span>` : nothing}
    </span>`;
  }

  _renderReceivers() {
    const rx = this._receivers;
    const placed = rx?.placed || [];
    const diag = this.data?.scanner_diagnostics || {};
    const floors = sortFloors(this.data?.layout?.floor || []).map((f) => f.name);
    for (const name of new Set(placed.map((r) => r.floor).filter(Boolean))) if (!floors.includes(name)) floors.push(name);
    const total = this._counts(placed);
    const attention = placed.filter((r) => this._status(r) !== "ok");
    const showCorr = placed.some((r) => r.correction != null);  // nothing applied yet: no empty column
    return html`<section class="card receivers">
      <h3>Proxies <span class="muted">${placed.length} placed</span></h3>
      <div class="row">
        ${this._countPills(total)}
        <span class="muted small">green online · yellow quiet (${fmtAge(QUIET_SECS)} without a reading) · red offline · orange unmatched, or behind (older firmware than most proxies: an update failed or never ran)</span>
        <span class="pill">${(rx?.unplaced || []).length} heard but unplaced</span>
        <span class="grow"></span>
        ${uiButton({ label: "Refresh", kind: "text", icon: "mdi:refresh", onClick: () => this._refresh() })}
      </div>
      ${attention.length ? html`<div class="attention">
        <b>Needs a look:</b> ${attention.map((r) => html`<span class="pill ${this._status(r) === "offline" ? "bad" : this._status(r) === "quiet" ? "quiet" : "warn"}" title=${r.firmware_behind && this._status(r) === "behind" ? `firmware behind: ${r.firmware_behind}` : this._status(r)}>${proxyName(this.data, r.address || r.slug)} · ${r.floor || "?"}${this._status(r) === "behind" ? " · firmware behind" : ""}</span>`)}
      </div>` : html`<div class="muted small">Every placed proxy is online and reporting.</div>`}
      ${floors.map((floor) => {
        const rows = placed.filter((r) => r.floor === floor);
        if (!rows.length) return nothing;
        const key = `floor:${floor}`;
        const rooms = new Map();
        for (const r of rows) { const room = this._roomOf(r) || "outside any room"; if (!rooms.has(room)) rooms.set(room, []); rooms.get(room).push(r); }
        const roomNames = [...rooms.keys()].sort((a, b) => (a === "outside any room") - (b === "outside any room") || a.localeCompare(b));
        return html`<div class="group">
          <button class="grouphead" @click=${() => this._toggle(key)}>
            <ha-icon icon=${this._open.has(key) ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon>
            <b>${floor}</b> <span class="muted small">${rows.length} proxies · ${rooms.size} rooms</span>
            <span class="grow"></span>${this._countPills(this._counts(rows))}
          </button>
          ${this._open.has(key) ? roomNames.map((room) => {
            const rr = rooms.get(room), rkey = `room:${floor}:${room}`;
            return html`<div class="room">
              <button class="grouphead sub" @click=${() => this._toggle(rkey)}>
                <ha-icon icon=${this._open.has(rkey) ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon>
                ${room} <span class="muted small">${rr.length}</span>
                <span class="grow"></span>${this._countPills(this._counts(rr))}
              </button>
              ${this._open.has(rkey) ? html`<div class="wrap"><table>
                <tr><th>Proxy</th><th>Status</th><th class="num">Last heard</th>${showCorr ? html`<th class="num" title="calibration correction factor">Corr.</th>` : nothing}<th class="num">Height</th></tr>
                ${rr.slice().sort((a, b) => (this._status(a) === "ok") - (this._status(b) === "ok") || a.slug.localeCompare(b.slug)).map((r) => {
                  const st = this._status(r);
                  return html`<tr>
                    <td><b>${proxyName(this.data, r.address || r.slug)}</b><br><span class="muted small">${r.slug}${r.address ? ` · ${r.address}` : ""}${r.firmware ? html`<br>${r.firmware}` : nothing}</span></td>
                    <td><span class="pill ${st === "ok" ? "ok" : st === "quiet" ? "quiet" : st === "offline" ? "bad" : "warn"}" title=${r.firmware_behind || st}>${st}</span></td>
                    <td class="num">${r.last_seen_age != null ? fmtAge(r.last_seen_age) : r.age != null ? fmtAge(r.age) : "—"}</td>
                    ${showCorr ? html`<td class="num">${r.correction != null ? fmtNum(r.correction, 3) : "—"}</td>` : nothing}
                    <td class="num">${r.height != null ? fmtLen(r.height, this.hass) : "—"}</td>
                  </tr>`;
                })}
              </table></div>` : nothing}
            </div>`;
          }) : nothing}
        </div>`;
      })}
      ${(rx?.unplaced || []).length ? html`<details><summary>Heard but not placed (${rx.unplaced.length})</summary>
        <ul class="plain">${rx.unplaced.map((u) => html`<li><b>${u.name || u.slug}</b> <span class="muted small">${u.address}${u.area ? ` · ${u.area}` : ""} · ${fmtAge(u.last_seen_age)} ago</span></li>`)}</ul></details>` : nothing}
      ${(diag.unmatched_receivers || []).length ? html`<details open><summary>Naming mismatches (${diag.unmatched_receivers.length})</summary>
        <ul class="plain">${diag.unmatched_receivers.map((u) => html`<li><b>${u.entity_id}</b> on ${u.floor}${u.suggested ? html` → suggested <code>${u.suggested}</code>` : nothing}</li>`)}</ul></details>` : nothing}
      <details @toggle=${(e) => { if (e.target.open && !this._linking) this._loadLinking(); }}><summary>What each proxy hears right now</summary>
        <p class="small muted">One row per placed proxy: which things it currently reports a distance for, and how far. <b>live</b> = it heard a tracked device in the last minute; <b>silent</b> = it is fine but nothing tracked is in its range right now (normal for a proxy in an empty room; worth a look only if it stays silent while people walk past it); <b>unmatched</b> = no Bermuda proxy has that name, so fix the placement on the Edit page. Unplaced proxies are not shown because their readings are never used.</p>
        ${this._linking ? html`<div class="wrap"><table>
          <tr><th>Proxy</th><th>Status</th><th class="num">Reporting</th><th>Things heard</th></tr>
          ${(this._linking.placed || []).map((p) => {
            const rows = (p.sensors || p.readings || []).filter((d) => d.state != null && d.state !== "unknown" && d.state !== "unavailable");
            return html`<tr>
              <td>${proxyName(this.data, p.address || p.entity_id || p.receiver || p.slug)}<br><span class="muted small">${p.floor || ""}</span></td>
              <td><span class="pill ${p.status === "live" ? "ok" : "warn"}">${p.status}</span></td>
              <td class="num">${p.reporting_count ?? rows.length} / ${p.sensor_count ?? (p.sensors || []).length}</td>
              <td class="small">${rows.length ? rows.map((d) => `${thingName(this.data, d.device || d.entity)} ${fmtLen(Number(d.state ?? d.distance), this.hass)}`).join(" · ") : html`<span class="muted">nothing tracked in range</span>`}</td>
            </tr>`;
          })}
        </table></div>` : html`<div class="muted small">Loading…</div>`}
      </details>
    </section>`;
  }

  _accPill(m) {
    return html`<span class="pill ${m < 2 ? "ok" : m < 4 ? "warn" : "bad"}">${fmtLen(m, this.hass, 2)}</span>`;
  }

  async _runAdvice() {
    this._busy = "advice";
    const r = await callWS(this, this.hass, { type: "sextant/advice" });
    this._busy = null;
    if (r) { this._advice = { ...r, at: Date.now() }; remember("advice", r); }
  }

  async _ignoreScanner(address, ignored) {
    const r = await callWS(this, this.hass, { type: "sextant/scanner/ignore", address, ignored });
    if (!r || !this._advice) return;
    // Keep the cached report in step without re-running the analysis.
    const a = this._advice;
    const moving = ignored ? (a.unplaced || []).find((u) => u.address === address) : (a.ignored || []).find((u) => u.address === address);
    const unplaced = ignored ? (a.unplaced || []).filter((u) => u.address !== address) : [...(a.unplaced || []), ...(moving ? [moving] : [])];
    this._advice = { ...a, unplaced, ignored: r.ignored };
    const { at, ...report } = this._advice;
    remember("advice", report);
  }

  // The Edit page, where the spots are pinned, is an administrator's; for
  // anyone else the button landed on Live with nothing to show.
  _isAdmin() { return this.hass?.user?.is_admin !== false; }

  _showSpots(floor, spots) {
    // sextant-edit labels each ring "add a proxy here · <room>" itself, so
    // several rooms' spots read fine together on one floor's plan.
    this.dispatchEvent(new CustomEvent("show-spots", { detail: { floor, spots: spots.map((s) => ({ floor, room: s.room, x: s.x, y: s.y, label: s.label })) }, bubbles: true, composed: true }));
  }

  /** advice rows grouped into one change plan per floor: the floor whose
   * flagged rooms are used most first, then worst floor first (a floor's
   * rank is its single worst room; ties broken by how many proxies it
   * needs). Each floor keeps the server's order among its own rooms. */
  _adviceByFloor(rooms) {
    const rank = { "no proxy": 0, "weak proxy": 1, "one-sided": 2, "coverage": 2, "noisy": 3, "ok": 4 };
    const byFloor = new Map();
    for (const r of rooms || []) {
      if (!byFloor.has(r.floor)) byFloor.set(r.floor, []);
      byFloor.get(r.floor).push(r);
    }
    return [...byFloor.entries()]
      .map(([floor, rows]) => ({
        floor, rows,
        use: Math.max(0, ...rows.filter((r) => r.issue !== "ok").map((r) => r.time_share || 0)),
        worst: Math.min(...rows.map((r) => rank[r.issue] ?? 9)),
        toAdd: rows.reduce((n, r) => n + (r.add || 0), 0),
        flagged: rows.filter((r) => r.issue !== "ok").length,
      }))
      .sort((a, b) => b.use - a.use || a.worst - b.worst || b.toAdd - a.toAdd || a.floor.localeCompare(b.floor));
  }

  _renderAdvice() {
    const a = this._advice;
    const issuePill = (issue) => html`<span class="pill ${issue === "ok" ? "ok" : issue === "noisy" || issue === "coverage" || issue === "one-sided" ? "warn" : "bad"}">${issue}</span>`;
    const floors = a ? this._adviceByFloor(a.rooms) : [];
    return html`<section class="card wide">
      <h3>Where a proxy would help</h3>
      <p class="small muted">Every room is judged two ways: how far its proxies land from where they are placed in the self-test, and whether any point in the room has three proxies near enough and around it. <b>Time here</b> is the room's share of the time people spent in these rooms, and <b>Bounces</b> how often someone was put into or out of it and straight back within two minutes, both from the person log; a dash is a room the log never names. Grouped into one change plan per floor, and the rooms that need something are listed most used first; a suggested spot is on a wall, where an outlet or a switch is. <b>Show on plan</b> pins one room's spots on the Edit page, <b>Show all on this floor</b> pins every spot on the floor at once.</p>
      <div class="row">${uiButton({ label: this._busy === "advice" ? "Analysing…" : a ? "Refresh" : "Analyse the house", kind: stale(a) || !a ? "primary" : "outline", disabled: this._busy === "advice", onClick: () => this._runAdvice() })}
        ${stale(a) ? html`<span class="pill warn" title="Auto calibration has sampled a lot since; refresh for a current picture">over an hour old</span>` : nothing}
        ${a ? html`<span class="muted small">${a.at ? `analysed ${fmtAge((Date.now() - a.at) / 1000)} ago · ` : ""}${a.summary.rooms} rooms · ${a.summary.to_add ? `${a.summary.to_add} proxies to add` : "nothing to add"}${Object.entries(a.summary.issues || {}).filter(([k]) => k !== "ok").map(([k, n]) => ` · ${n} ${k}`).join("")}${a.usage_hours ? ` · room use over ${a.usage_hours} h` : ""}</span>` : nothing}</div>
      ${a?.unplaced?.length ? html`<div class="row"><b>Heard but not placed:</b>
        ${a.unplaced.map((u) => html`<span class="chips">${u.name}${u.suggest ? html` <span class="muted small">→ ${u.suggest.room} (${u.suggest.floor})</span> ${this._isAdmin() ? uiButton({ label: "Show on plan", kind: "text", onClick: () => this._showSpots(u.suggest.floor, [{ room: u.suggest.room, x: u.suggest.x, y: u.suggest.y }]) }) : nothing}` : nothing} ${this._isAdmin() ? uiButton({ label: "Ignore", kind: "text", title: "Leave this scanner out of the unplaced lists (a kiosk, a test board, an outdoor proxy)", onClick: () => this._ignoreScanner(u.address, true) }) : nothing}</span>`)}</div>` : nothing}
      ${a?.ignored?.length ? html`<div class="row muted small">Ignored: ${a.ignored.map((u) => html`<span class="chips">${u.name} ${this._isAdmin() ? uiButton({ label: "Un-ignore", kind: "text", onClick: () => this._ignoreScanner(u.address, false) }) : nothing}</span>`)}</div>` : nothing}
      ${a ? floors.map(({ floor, rows, toAdd, flagged }) => {
        const allSpots = rows.flatMap((r) => (r.spots || []).map((s) => ({ ...s, room: r.room })));
        return html`<div class="floorplan">
          <h4>${floor} <span class="muted small">${flagged ? `${flagged} room${flagged === 1 ? "" : "s"} flagged` : "every room fine"}${toAdd ? ` · ${toAdd} to add` : ""}</span>
            ${allSpots.length && this._isAdmin() ? uiButton({ label: `Show all ${allSpots.length} on this floor`, kind: "outline", onClick: () => this._showSpots(floor, allSpots) }) : nothing}
          </h4>
          <div class="wrap"><table>
            <tr><th>Room</th><th>Issue</th><th class="num">Proxies</th><th class="num">Median</th><th class="num">Time here</th><th class="num">Bounces</th><th class="num">Add</th><th>What to do</th><th></th></tr>
            ${rows.map((r) => html`<tr>
              <td>${r.room}</td><td>${issuePill(r.issue)}</td>
              <td class="num">${r.proxies}${r.solved < r.proxies ? html` <span class="muted small">(${r.solved} solved)</span>` : nothing}</td>
              <td class="num">${r.median_m != null ? fmtLen(r.median_m, this.hass, 2) : "—"}</td>
              <td class="num">${r.time_share != null ? `${fmtNum(r.time_share * 100, 1)}%` : "—"}</td>
              <td class="num">${r.bounces ?? "—"}</td>
              <td class="num">${r.add || ""}</td>
              <td class="small">${r.note ? r.note.replace(/[a-z0-9_]+_(rrn00|s2224|eth|shelly)[a-z0-9_]*/g, (m) => proxyName(this.data, m)) : html`<span class="muted">fine</span>`}</td>
              <td>${r.spots?.length && this._isAdmin() ? uiButton({ label: "Show on plan", kind: "text", onClick: () => this._showSpots(r.floor, r.spots.map((s) => ({ ...s, room: r.room }))) }) : nothing}</td>
            </tr>`)}
          </table></div>
        </div>`;
      }) : html`<p class="muted small">Runs the self-test (a few seconds) and reads the plan.</p>`}
    </section>`;
  }

  _renderSelftest() {
    const st = this._selftest;
    const bd = st?.breakdown;
    const solved = st?.result?.receivers || [];
    const unsolved = st?.result?.unsolved || [];
    const cell = (m) => (m != null ? fmtLen(m, this.hass, 2) : "—");
    // A floor whose every proxy is unsolved with nobody hearing it has no
    // calibration samples at all (the window holds the last manual run's
    // floor unless Auto calibration is on), which is a different message
    // from "the geometry did not converge".
    const noSamples = new Set((bd?.floors || []).filter((f) => !f.solved && f.unsolved
      && unsolved.filter((u) => u.floor === f.floor).every((u) => !u.heard_by)).map((f) => f.floor));
    const count = (r) => (r.solved || r.unsolved
      ? html`${r.solved}${r.unsolved ? html` <span class="muted small">+${r.unsolved} unsolved</span>` : nothing}`
      : html`<span class="muted small">no proxy</span>`);
    return html`<section class="card">
      <h3>Proxy self-test</h3>
      <p class="small muted">Leave-one-out: each proxy is located from the others' ranges to it and compared with where it is placed. Read it by room: a whole-house figure hides which rooms the proxies place well and which they do not. It works from the calibration sample window, so a floor only has figures once it has been sampled: turn on <b>Auto calibration</b> below to keep every floor sampled.</p>
      <div class="row">${uiButton({ label: this._busy === "selftest" ? "Running…" : st ? "Refresh" : "Run self-test", kind: stale(st) || !st ? "primary" : "outline", disabled: this._busy === "selftest", onClick: () => this._runSelftest() })}
        ${stale(st) ? html`<span class="pill warn">over an hour old</span>` : nothing}
        ${st && st.state != null ? html`<span class="muted small">${st.at ? `run ${fmtAge((Date.now() - st.at) / 1000)} ago · ` : ""}whole house</span> ${this._accPill(Number(st.state))}` : nothing}</div>
      ${bd ? html`<div class="wrap"><table>
        <tr><th>Floor / room</th><th class="num">Proxies</th><th class="num">Median</th><th class="num">CEP95</th><th>Worst proxy</th></tr>
        ${bd.floors.map((f) => html`
          <tr class="grouphead"><td><b>${f.floor}</b></td><td class="num">${count(f)}</td><td class="num">${cell(f.cep50_m)}</td><td class="num">${f.cep95_m != null ? this._accPill(f.cep95_m) : "—"}</td><td>${noSamples.has(f.floor) ? html`<span class="muted small">no calibration samples for this floor yet</span>` : f.worst ? proxyName(this.data, f.worst) : ""}</td></tr>
          ${bd.rooms.filter((r) => r.floor === f.floor).map((r) => html`<tr><td style="padding-left: 22px">${r.room ?? html`<span class="muted">outside any room</span>`}</td><td class="num">${count(r)}</td><td class="num">${cell(r.cep50_m)}</td><td class="num">${r.cep95_m != null ? this._accPill(r.cep95_m) : "—"}</td><td>${r.worst ? proxyName(this.data, r.worst) : ""}</td></tr>`)}`)}
      </table></div>
      ${solved.filter((v) => v.misplaced).map((v) => html`<div class="row"><span class="pill warn">placement?</span>
        <span><b>${proxyName(this.data, v.entity)}</b> is drawn in ${v.room ?? v.floor}, but ${v.heard_by} proxies agree it is ${fmtLen(v.error_m, this.hass, 1)} away${v.est_room && v.est_room !== v.room ? html`, in ${v.est_room}` : nothing}. <span class="muted small">Their ranges miss that spot by ${fmtLen(v.fit_m, this.hass, 1)} and the drawn one by ${fmtLen(v.placed_fit_m, this.hass, 1)}.</span></span>
        ${uiButton({ label: "Move it there", kind: "outline", disabled: !!this._busy, onClick: () => this._moveProxy(v) })}</div>`)}
      <details><summary>Every proxy (${solved.length} solved${unsolved.length ? `, ${unsolved.length} unsolved` : ""})</summary>
        <div class="wrap"><table><tr><th>Proxy</th><th>Room</th><th class="num">Error</th><th class="num">Heard by</th></tr>
          ${[...solved].sort((a, b) => (b.error_m ?? -1) - (a.error_m ?? -1)).map((v) => html`<tr><td>${proxyName(this.data, v.entity)}</td><td class="muted">${v.floor}${v.room ? ` · ${v.room}` : ""}</td><td class="num">${fmtLen(v.error_m, this.hass, 2)}</td><td class="num">${v.heard_by}</td></tr>`)}
          ${unsolved.map((v) => html`<tr><td>${proxyName(this.data, v.entity)}</td><td class="muted">${v.floor}${v.room ? ` · ${v.room}` : ""}</td><td class="num"><span class="muted">unsolved${v.reason ? ` (${v.reason})` : ""}</span></td><td class="num">${v.heard_by}</td></tr>`)}
        </table></div>
      </details>` : nothing}
    </section>`;
  }

  // --- Receivers against real fixes -------------------------------------------------

  _renderReport() {
    if (!this._isAdmin()) return nothing;
    const r = this._report;
    // Worst first: the receivers whose ranges disagree most with the fixes.
    const rows = [...(r?.rows || [])].sort((a, b) => Math.abs(b.bias_m) - Math.abs(a.bias_m));
    const len = (m) => `${m > 0 ? "+" : ""}${fmtLen(m, this.hass, 1)}`;
    return html`<section class="card">
      <h3>Receivers against real fixes</h3>
      <p class="small muted">Each receiver's ranges set against the fixes they went into, from the election log: a receiver that reads far short or long of where things were placed is misplaced or needs calibrating. Unlike the self-test this uses the things you track, not the proxies hearing each other. It needs the election log (Tuning, Election log hours). A fix that came mostly from fingerprints can make a healthy receiver look off, so trust a receiver that is off across many readings.</p>
      <div class="row">${uiButton({ label: this._busy === "report" ? "Reading…" : r ? "Refresh" : "Read the last 6 hours", kind: r ? "outline" : "primary", disabled: !!this._busy, onClick: () => this._runReport() })}</div>
      ${r && !rows.length ? html`<p class="small muted">Nothing to read: the election log holds no range fixes for the last ${r.hours} hours.</p>` : nothing}
      ${rows.length ? html`<div class="wrap"><table>
        <tr><th>Receiver</th><th>Floor</th><th class="num">Heard</th><th class="num">Reads</th><th class="num">Off by</th></tr>
        ${rows.slice(0, 12).map((v) => html`<tr><td>${proxyName(this.data, v.receiver)}</td><td class="muted">${v.floor}</td><td class="num">${v.heard}</td>
          <td class="num">${Math.abs(v.bias_m) >= 2 ? html`<span class="pill warn">${len(v.bias_m)}</span>` : len(v.bias_m)}</td><td class="num">${fmtLen(v.off_m, this.hass, 1)}</td></tr>`)}
      </table></div>
      <p class="small muted">Reads: the usual gap between its range and the distance to the fix (minus is short). Off by: the typical size of that gap. ${rows.length > 12 ? `The worst 12 of ${rows.length}.` : ""}</p>` : nothing}
      ${r?.silent?.length ? html`<details><summary>${r.silent.length} placed receiver${r.silent.length === 1 ? "" : "s"} in no fix</summary>
        <p class="small">${r.silent.map((v) => `${proxyName(this.data, v.receiver)} (${v.floor})`).join(", ")}</p></details>` : nothing}
    </section>`;
  }

  // --- Wi-Fi signal by room --------------------------------------------------------

  /** A signal level as a pill: good from -60 dBm up, weak below -70. */
  _dbmPill(dbm) {
    return html`<span class="pill ${dbm >= -60 ? "ok" : dbm >= -70 ? "warn" : "bad"}">${fmtNum(dbm, 0)} dBm</span>`;
  }

  _renderWifiRooms() {
    // (the dBm cells stay on one line: a pill split over two is unreadable)
    const h = this._wifiHeat;
    if (!h || !this._isAdmin()) return nothing;
    const rooms = h.rooms || [];
    const offsets = Object.entries(h.bias || {}).filter(([, v]) => Math.abs(v) >= 0.5);
    return html`<section class="card">
      <h3>Wi-Fi signal by room</h3>
      <p class="small muted">What phones, watches and the proxies on the Wi-Fi actually get, where Sextant has placed them: the median of each room's one-metre squares, weakest first. It is the signal to the access point each one is on. The map itself is on the Live page (the Wi-Fi signal switch).</p>
      ${rooms.length ? html`<div class="wrap"><table class="p-5">
        <tr><th>Room</th><th class="num">Median</th><th class="num">Weakest</th><th>Mostly on</th><th class="num">Squares</th></tr>
        ${rooms.map((r) => html`<tr><td>${r.room} <span class="muted small">${r.floor}<span class="ponly"> · ${r.cells} sq</span></span></td><td class="num nowrap">${this._dbmPill(r.dbm)}</td><td class="num nowrap">${fmtNum(r.worst, 0)} dBm</td><td>${h.aps?.[r.ap] || r.ap}</td><td class="num">${r.cells}</td></tr>`)}
      </table></div>` : html`<p class="small">No room has enough samples yet. The proxies on the Wi-Fi fill their own squares within minutes; phones and watches fill the rooms people use over a few days.</p>`}
      ${Object.keys(h.field?.models || {}).length ? html`<p class="small muted">The Live page's estimate between the measured squares is a model of each placed access point fitted to them, each Wi-Fi band on its own once it has a dozen squares: ${Object.entries(h.field.models).map(([b, m]) => `${b === "mixed" ? "all bands together" : `${b} GHz`}, walls ${fmtNum(m.wall, 1)} dB and a floor ${fmtNum(m.floor, 0)} dB, typically ${fmtNum(m.rms, 0)} dB off (${m.used} squares)`).join("; ")}. Most of what is left is the devices: a proxy's own transmit strength differs from the next by as much, and one that never moves cannot be told apart from where it is. Phones and watches walking about pin it down.</p>` : nothing}
      <div class="row small muted">${fmtNum(h.samples || 0, 0)} samples so far${offsets.length ? html` · learned offsets: ${offsets.map(([n, v]) => `${n} ${v > 0 ? "+" : ""}${fmtNum(v, 1)} dB`).join(", ")}` : nothing}
        <span class="grow"></span>${uiButton({ label: "Start over", kind: "text", onClick: () => this._clearWifiHeat(), title: "Drop every sample: after moving or replacing access points" })}</div>
    </section>`;
  }

  // --- Calibration ---------------------------------------------------------------

  _renderCalibration() {
    const cal = this._cal;
    const results = cal?.results || {};
    const sampling = cal?.state === "sampling";
    const floor = this._calFloor;
    const cur = results[floor];
    // "Worse" = the self-test says this solve would not place the floor's
    // proxies better than what is in place (or than nothing); without a
    // verdict, the fit's own error factor decides.
    const judged = (r) => (r?.selftest ? r.selftest.new_m > Math.min(r.selftest.none_m, r.selftest.current_m ?? Infinity) : !!r && r.error_factor_after > r.error_factor_before);
    const worse = judged(cur);
    const verdict = (r) => (r?.selftest ? html` <span class="muted small">self-test median: none ${fmtLen(r.selftest.none_m, this.hass, 2)}${r.selftest.current_m != null ? ` · in place ${fmtLen(r.selftest.current_m, this.hass, 2)}` : ""} · this solve ${fmtLen(r.selftest.new_m, this.hass, 2)}</span>` : nothing);
    const decision = (name) => { const d = cal?.auto_decisions?.[name]; return d ? html` <span class="pill ${d.action === "apply" ? "ok" : d.action === "revert" ? "warn" : ""}" title=${d.reason}>auto: ${d.action === "apply" ? "applied" : d.action === "revert" ? "removed its corrections" : "held back"}</span>` : nothing; };
    return html`<section class="card wide">
      <h3>Proxy calibration <span class="muted small">${floor ? `for ${floor}, picked in the header` : ""}</span></h3>
      <p class="small muted">Every proxy hears every other proxy's beacon at a known distance; a run collects those readings and solves one range correction per proxy. Apply only when the error factor after is lower than before, otherwise the corrections are absorbing placement error, not radio bias.</p>
      ${cal ? html`
        <div class="row">
          <span class="pill ${sampling ? "warn" : cal.mode === "auto" ? "ok" : ""}">${cal.mode === "auto" ? `auto${cal.started_at ? ` · sampling for ${fmtAge(Date.now() / 1000 - cal.started_at)}` : ""}${cal.started_at && !cal.last_solved_at && cal.first_solve_after ? ` · first solve in ${fmtAge(Math.max(0, cal.started_at + cal.first_solve_after - Date.now() / 1000))}` : ""}` : cal.state}${sampling && cal.seconds_left != null ? ` · ${fmtAge(cal.seconds_left)} left` : ""}</span>
          <span class="muted small">${Object.keys(cal.pair_counts || {}).length} pairs sampled · ${cal.receiver_count} proxies${cal.last_solved_at ? ` · solved ${fmtAge(Date.now() / 1000 - cal.last_solved_at)} ago` : ""}</span>
          ${cal.error ? html`<span class="pill bad">${cal.error}</span>` : nothing}
        </div>
        <div class="row">
          ${uiField({ label: "Duration (s)", type: "number", min: 60, max: 3600, step: 30, value: this._calDuration, onChange: (v) => { this._calDuration = Number(v); }, style: "width: 130px" })}
          ${uiButton({ label: "Start run", kind: "primary", disabled: sampling || !!this._busy, onClick: () => this._calAction("start", { floor, duration: this._calDuration }) })}
          ${uiButton({ label: "Cancel", kind: "text", disabled: !!this._busy, onClick: () => this._calAction("cancel") })}
          <span class="chips">${uiSwitch({ label: "Auto calibration", checked: cal.mode === "auto", onChange: (v) => this._calAction("auto", { enabled: v }) })}</span>
        </div>
        <div class="row">
          ${uiButton({ label: "Solve now", disabled: !!this._busy, onClick: () => this._calAction("solve", { floor }) })}
          ${uiButton({ label: worse ? "Apply anyway" : "Apply corrections", kind: worse ? "danger" : "outline", icon: worse ? "mdi:alert" : undefined, disabled: !!this._busy || !cur,
            title: worse ? `This solve made ${floor} worse (×${fmtNum(cur.error_factor_before, 2)} → ×${fmtNum(cur.error_factor_after, 2)}); the corrections are absorbing placement error` : cur ? `Store the ${floor} factors with the layout` : "Solve a floor first",
            onClick: async () => { if (!worse || await confirmAsync(`This solve made ${floor} worse: error ×${fmtNum(cur.error_factor_before, 2)} → ×${fmtNum(cur.error_factor_after, 2)}. Corrections that make the fit worse are absorbing placement error, not radio bias. Apply anyway?`, { ok: "Apply anyway", danger: true })) this._calAction("apply", { floor }); } })}
          ${uiButton({ label: "Reset", kind: "danger", disabled: !!this._busy, onClick: async () => { if (await confirmAsync(`Reset corrections on ${floor}?`, { ok: "Reset", danger: true })) this._calAction("reset", { floor }); } })}
        </div>
        ${Object.entries(results).map(([name, r]) => html`<details ?open=${name === floor}>
          <summary>${name}: ${r.pairs_used} pairs, error ×${fmtNum(r.error_factor_before, 2)} → ×${fmtNum(r.error_factor_after, 2)}${judged(r) ? html` <span class="pill warn">would not help: do not apply</span>` : nothing}${r.low_confidence?.length ? html` <span class="pill warn">${r.low_confidence.length} low confidence</span>` : nothing}${decision(name)}${verdict(r)}</summary>
          <div class="wrap"><table><tr><th>Proxy</th><th class="num">Factor</th><th class="num">≈ dB</th></tr>
            ${Object.entries(r.receivers || {}).sort((a, b) => Math.abs(b[1] - 1) - Math.abs(a[1] - 1)).map(([slug, f]) => html`<tr><td>${proxyName(this.data, slug)}${(r.low_confidence || []).includes(slug) ? html` <span class="pill warn">low</span>` : nothing}</td><td class="num">${fmtNum(f, 3)}</td><td class="num">${fmtNum(r.rx_bias_db_equident?.[slug], 1)}</td></tr>`)}
          </table></div>
          ${(r.missing_no_data || []).length ? html`<p class="small muted">No samples: ${r.missing_no_data.join(", ")}</p>` : nothing}
          ${(r.missing_unmatched || []).length ? html`<p class="small muted">Unmatched: ${r.missing_unmatched.join(", ")}</p>` : nothing}
        </details>`)}
      ` : html`<div class="muted">Loading…</div>`}
    </section>`;
  }

  // --- Tuning --------------------------------------------------------------------

  _renderKpi() {
    const k = this._kpi;
    const s = k?.summary || {};
    const d = k?.deltas;
    const ents = Object.entries(k?.entities || {}).filter(([e]) => e.endsWith("_sextant_room")).sort((a, b) => (b[1].changes_per_hour ?? 0) - (a[1].changes_per_hour ?? 0));
    // Fewer changes / flips is better (green); a longer dwell is better.
    const lessIsBetter = (v, digits = 1, scale = 1) => v == null ? "—" : html`<span class=${v < 0 ? "good" : v > 0 ? "bad" : ""}>${v > 0 ? "+" : ""}${fmtNum(v * scale, digits)}</span>`;
    const moreIsBetter = (v) => v == null ? "—" : html`<span class=${v > 0 ? "good" : v < 0 ? "bad" : ""}>${v > 0 ? "+" : "−"}${fmtAge(Math.abs(v))}</span>`;
    const sz = d?.summary?.sextant_room;
    const baselineOptions = [{ value: "", label: "no baseline" }, ...this._baselines.map((b) => ({ value: b.name, label: `${b.name} · ${b.hours} h · ${(b.saved_at || "").slice(0, 10)}` }))];
    const name = (e) => thingName(this.data, e.replace(/^sensor\./, "").replace(/_sextant_room$/, ""));
    return html`<section class="card wide">
      <h3>Stability</h3>
      <div class="row">
        ${uiSelect({ label: "Window", value: this._kpiHours, options: [1, 3, 6, 12, 24, 48].map((h) => ({ value: h, label: `${h} h` })), onChange: (v) => { this._kpiHours = Number(v); }, style: "min-width: 110px" })}
        ${uiSelect({ label: "Compare with", value: this._baseline, options: baselineOptions, onChange: (v) => { this._baseline = v; }, style: "min-width: 240px" })}
        ${uiButton({ label: this._busy === "kpi" ? "Computing…" : "Compute", kind: "primary", disabled: this._busy === "kpi", onClick: () => this._runKpi() })}
        ${s.sextant_room ? html`<span class="pill">${s.sextant_room.changes_per_thing_hour} room changes / thing-h</span>
          <span class="pill">flip ratio ${s.sextant_room.flip_ratio}</span><span class="pill">median dwell ${fmtAge(s.sextant_room.median_of_median_dwell_s)}</span>
          ${s.sextant_room.far_moves_per_thing_day != null ? html`<span class="pill" title=${FAR_MOVES_HELP}>${fmtNum(s.sextant_room.far_moves_per_thing_day, 1)} far moves / thing-day</span>` : nothing}` : nothing}
        ${sz ? html`<span class="pill" title="this window minus the baseline">vs ${k.baseline.name}: ${lessIsBetter(sz.changes_per_thing_hour, 2)} chg/thing-h · ${lessIsBetter(sz.flip_ratio, 0, 100)} flip pts · ${moreIsBetter(sz.median_of_median_dwell_s)} dwell${sz.far_moves_per_thing_day != null ? html` · ${lessIsBetter(sz.far_moves_per_thing_day, 1)} far/day` : nothing}</span>` : nothing}
      </div>
      <div class="row">
        ${uiField({ label: "Save this window as a baseline", value: this._baselineName, placeholder: "e.g. fused 2026-09-17", onChange: (v) => { this._baselineName = v; }, style: "width: 260px" })}
        ${uiButton({ label: this._busy === "baseline" ? "Saving…" : "Save baseline", disabled: this._busy === "baseline" || !(this._baselineName || "").trim(), onClick: () => this._saveBaseline(), title: "Computes the selected window now and keeps it for later comparison" })}
        ${this._baseline ? uiButton({ label: "Delete baseline", kind: "danger", onClick: () => this._deleteBaseline(this._baseline) }) : nothing}
      </div>
      ${ents.length ? html`<div class="wrap"><table>
        <tr><th>Thing</th><th class="num">chg/h</th><th class="num">flip %</th><th class="num">dwell</th><th class="num">&lt;60 s %</th><th class="num" title=${FAR_MOVES_HELP}>far/day</th><th class="num">dead</th>${d ? html`<th class="num">Δ chg/h</th><th class="num">Δ flip pts</th><th class="num">Δ dwell</th><th class="num" title=${FAR_MOVES_HELP}>Δ far/day</th>` : nothing}</tr>
        ${ents.map(([e, m]) => html`<tr><td>${name(e)}</td><td class="num">${fmtNum(m.changes_per_hour, 1)}</td><td class="num">${m.flip_ratio != null ? fmtNum(m.flip_ratio * 100, 0) : "—"}</td><td class="num">${fmtAge(m.median_dwell_s)}</td><td class="num">${m.short_dwell_ratio != null ? fmtNum(m.short_dwell_ratio * 100, 0) : "—"}</td><td class="num">${m.far_moves_per_day != null ? fmtNum(m.far_moves_per_day, 1) : "—"}</td><td class="num">${m.dead}</td>${d ? html`<td class="num">${lessIsBetter(d.entities?.[e]?.changes_per_hour, 1)}</td><td class="num">${lessIsBetter(d.entities?.[e]?.flip_ratio, 0, 100)}</td><td class="num">${moreIsBetter(d.entities?.[e]?.median_dwell_s)}</td><td class="num">${lessIsBetter(d.entities?.[e]?.far_moves_per_day, 1)}</td>` : nothing}</tr>`)}
      </table></div>` : k ? html`<div class="muted small">No room sensors in the recorder window.</div>` : nothing}
    </section>`;
  }

  async _runAccuracy() {
    this._busy = "accuracy";
    const r = await callWS(this, this.hass, { type: "sextant/truth/evaluate" });
    this._busy = null;
    if (r) this._accuracy = r;
  }

  async _runPinHealth() {
    this._busy = "pins";
    const r = await callWS(this, this.hass, { type: "sextant/truth/health" });
    this._busy = null;
    if (r) this._pinHealth = r;
  }

  /** Forget the given flagged pins (after one confirmation), then check again:
   * every other row was worked out with those pins in place. */
  async _forgetPins(ids, what) {
    if (!(await confirmAsync(`Forget ${what}? This cannot be undone.`, { ok: "Forget", danger: true }))) return;
    this._busy = "pins";
    const gone = [];
    for (const id of ids) if (await callWS(this, this.hass, { type: "sextant/truth/delete", mark_id: id })) gone.push(id);
    if (gone.length) toast(this, `${gone.length} pin${gone.length === 1 ? "" : "s"} forgotten`);
    // Off the card now: the check below can fail, and a forgotten pin must not stay listed.
    if (this._pinHealth) this._pinHealth = { ...this._pinHealth, pins: (this._pinHealth.pins || []).filter((p) => !gone.includes(p.id)) };
    await this._runPinHealth();
  }

  _renderPinHealth() {
    const h = this._pinHealth;
    const why = (p) => [
      p.reasons.includes("hurts") ? `${p.hurts} of the ${p.used_by} pin${p.used_by === 1 ? "" : "s"} it guides land${p.hurts === 1 ? "s" : ""} further off with it, ${fmtLen(p.net_m, this.hass, 1)} on average${p.worst ? ` (pin ${p.worst.id} by ${fmtLen(p.worst.m, this.hass, 1)})` : ""}. One of them may be in the wrong place, or the two places look alike to Bluetooth: check both.` : "",
      p.reasons.includes("far") ? `Its own readings put it ${fmtLen(p.own_m, this.hass, 1)} from the pin, far more than your other pins: it was probably not there the whole time.` : "",
      p.reasons.includes("duplicate") ? `A copy of pin ${p.duplicate_of}, from the same readings.` : "",
    ].filter(Boolean).join(" ");
    const copies = (h?.pins || []).filter((p) => p.reasons.length === 1 && p.reasons[0] === "duplicate").map((p) => p.id);
    const where = (g) => `${g.room || "outside every room"} (${g.floor})`;
    return html`<section class="card wide">
      <h3>Location pins</h3>
      <p class="small muted">A pin (Live page, "It's actually here…") is the best help a place can get: fixes within about ${fmtLen(2, this.hass, 0)} of one land much closer. A pin in the wrong place does the opposite and pulls everything near it the wrong way. (A pin only guides a thing whose position uses the fingerprint match: "Apply best fit" after pinning turns that on when it lands closer.) The check looks for both: pins that make their neighbours land worse, and places where a thing rests with no pin near.</p>
      <div class="row">${uiButton({ label: this._busy === "pins" ? "Checking…" : h ? "Check again" : "Check pins", kind: h ? "outline" : "primary", disabled: this._busy === "pins", onClick: () => this._runPinHealth() })}
        ${h ? html`<span class="muted small">${h.checked} pin${h.checked === 1 ? "" : "s"} checked · ${h.pins.length ? `${h.pins.length} to look at again` : "none to look at again"} · ${h.gaps.length ? `${h.gaps.length} place${h.gaps.length === 1 ? "" : "s"} without a pin` : "no resting place without a pin"}</span>` : nothing}</div>
      ${h?.pins.length ? html`<h4>Pins to look at again</h4><div class="wrap"><table>
        <tr><th class="num">Pin</th><th>Thing</th><th>Floor</th><th>Placed</th><th>Why</th><th></th></tr>
        ${h.pins.map((p) => html`<tr><td class="num">${p.id}</td><td>${thingName(this.data, p.entity)}</td><td>${p.floor}</td><td>${p.t ? new Date(p.t * 1000).toLocaleDateString() : "—"}</td>
          <td class="small">${why(p)}</td><td>${uiButton({ label: "Forget", kind: "text", disabled: this._busy === "pins", onClick: () => this._forgetPins([p.id], `pin ${p.id}`) })}</td></tr>`)}
      </table></div>
      ${copies.length > 1 ? html`<div class="row">${uiButton({ label: `Forget the ${copies.length} copies`, kind: "outline", disabled: this._busy === "pins", onClick: () => this._forgetPins(copies, `the ${copies.length} copies`) })}</div>` : nothing}` : nothing}
      ${h?.gaps.length ? html`<h4>Places without a pin <span class="muted small">from the last ${fmtAge(h.history_hours * 3600)} of history</span></h4>
      <p class="small muted">The ring on the plan is where Sextant put the thing, which is only roughly where it was. Next time it is there, pin it at its real spot on the Live page.</p>
      <div class="wrap"><table>
        <tr><th>Thing</th><th>Rests in</th><th class="num">Time there</th><th class="num">Nearest pin</th><th></th></tr>
        ${h.gaps.map((g) => html`<tr><td>${thingName(this.data, g.entity)}</td><td>${where(g)}</td><td class="num">${fmtAge(g.hours * 3600)}</td>
          <td class="num">${g.nearest_pin_m != null ? fmtLen(g.nearest_pin_m, this.hass, 1) : "none on this floor"}</td>
          <td>${uiButton({ label: "Show on plan", kind: "text", onClick: () => this._showSpots(g.floor, [{ x: g.x, y: g.y, room: g.room, label: `pin ${thingName(this.data, g.entity)} when it is here` }]) })}</td></tr>`)}
      </table></div>` : nothing}
    </section>`;
  }

  _renderAccuracy() {
    const a = this._accuracy;
    const rows = Object.entries(a?.things || {}).sort((x, y) => y[1].mean_m - x[1].mean_m);
    return html`<section class="card wide">
      <h3>Accuracy <span class="muted small">against your location pins</span></h3>
      <p class="small muted">Every pin (Live page, "It's actually here…") re-solved under the settings in force now: how far each thing lands from where you said it was, and how often it gets the room right.</p>
      <div class="row">${uiButton({ label: this._busy === "accuracy" ? "Evaluating…" : "Evaluate pins", kind: "primary", disabled: this._busy === "accuracy", onClick: () => this._runAccuracy() })}
        ${a ? html`<span class="pill">${(a.marks || []).length} pin${(a.marks || []).length === 1 ? "" : "s"}</span>` : nothing}</div>
      ${rows.length ? html`<div class="wrap"><table>
        <tr><th>Thing</th><th class="num">Pins</th><th class="num">Mean error</th><th class="num">Right room</th></tr>
        ${rows.map(([e, m]) => html`<tr><td>${thingName(this.data, e)}</td><td class="num">${m.marks}</td><td class="num">${fmtLen(m.mean_m, this.hass)}</td><td class="num">${Math.round(m.room_ok * 100)}%</td></tr>`)}
      </table></div>` : a ? html`<div class="muted small">No pins yet.</div>` : nothing}
    </section>`;
  }

  _renderTuning() {
    const spec = this.data?.tuning_spec || {};
    const groups = [
      ["Estimator", ["position_estimator", "fingerprint_weight", "fingerprint_floor_weight", "fingerprint_k", "fingerprint_missing_m", "fingerprint_ref_gain", "fingerprint_auto_gain", "fingerprint_marks", "fingerprint_marks_scope", "distance_estimator", "median_window_secs", "median_min_samples", "stale_interval_factor", "range_auto_scale"]],
      ["Solver", ["solver_max_receivers", "solver_max_range", "solver_near_always"]],
      ["Rooms", ["zone_hysteresis", "zone_prob_smoothing", "zone_switch_margin", "zone_switch_secs", "far_move_margin", "far_move_secs", "stationary_speed", "stationary_secs", "zone_unlock_margin", "zone_unlock_secs", "zone_lock_warmup_secs", "outside_margin_m", "outside_secs", "outside_faint_prox", "outside_faint_m", "outside_near_m"]],
      ["Spots", ["subzone_switch_secs", "subzone_enter_prob", "subzone_unlock_margin", "subzone_lock_release_m", "spot_proxy_near_m", "spot_proxy_far_m", "spot_proxy_ratio"]],
      ["Near-field anchor", ["anchor_max_m", "anchor_ratio", "anchor_secs", "anchor_release_m", "zone_anchor_inset_m"]],
      ["Floors", ["floor_switch_secs", "floor_switch_margin", "floor_tenure_bonus", "floor_tenure_full_secs", "floor_proximity_weight", "floor_proximity_blend", "floor_proximity_k", "wifi_floor_weight"]],
      ["People", ["gps_stale_secs", "gps_leave_m", "exit_quiet_secs", "exit_door_secs", "watch_still_secs", "wifi_confirm_secs", "person_log_hours"]],
      ["Occupancy", ["room_hold_secs", "room_extended_secs", "room_sleep_hold_secs", "room_extended_hold_secs", "room_force_max_secs", "sleep_start_hour", "sleep_end_hour",
        "door_hold_max_secs", "door_settle_secs", "sensor_gone_secs", "sensor_stuck_secs"]],
      ["Robots and mmWave", ["robot_poll_secs", "mmwave_fusion", "mmwave_auto_pins", "mmwave_rooms", "mmwave_pair_m", "mmwave_merge_m", "mmwave_tick_s", "mmwave_verify_s", "mmwave_hold_s"]],
      ["Calibration", ["calibration_target", "correction_close_fade", "correction_fade_near_m", "correction_fade_far_m"]],
      ["History and display", ["history_hours", "stale_after_secs", "away_after_secs", "restore_state_secs", "election_log_hours"]],
    ];
    const known = new Set(groups.flatMap((g) => g[1]));
    const rest = Object.keys(spec).filter((k) => !known.has(k));
    if (rest.length) groups.push(["Other", rest]);
    const field = (key) => {
      const s = spec[key];
      if (!s) return nothing;
      const v = this._tuning[key];
      const set = (value) => { this._tuning = { ...this._tuning, [key]: value }; };
      const [label, help] = TUNING_LABELS[key] || [key, ""];
      if (!tuningMatches(key, label, help, this._tfilter)) return nothing;
      const changed = tuningChanged(v, s.default);
      let control;
      if (s.type === "bool") control = html`<span class="chips">${uiSwitch({ label, checked: v == null ? !!s.default : !!v, onChange: set })}</span>`;
      else if (s.type === "str") control = uiSelect({ label, value: v ?? s.default, options: s.choices.map((c) => ({ value: c, label: c })), onChange: set, style: "min-width: 220px" });
      else control = uiField({ label, type: "number", step: s.type === "int" ? 1 : "any", min: s.min, max: s.max, placeholder: String(s.default), value: v == null ? "" : v, onChange: (val) => set(val === "" ? null : Number(val)), style: "width: 220px" });
      const reset = () => { const t = { ...this._tuning }; delete t[key]; this._tuning = t; };
      return html`<div class="tfield">${control}
        <code class="hint">${key}${changed ? html` <span class="chg">changed</span> <a class="treset" href="#" @click=${(e) => { e.preventDefault(); reset(); }}>reset</a>` : nothing}</code>
        <span class="thelp">${tuningHelpLine(key, help, s.default, isImperial(this.hass))}${key === "election_log_hours" && this._logUse?.files ? ` On disk now: ${fmtNum(this._logUse.bytes / 1048576, 0)} MB in ${this._logUse.files} files.` : ""}</span></div>`;
    };
    const shown = (keys) => keys.filter((k) => spec[k] && tuningMatches(k, (TUNING_LABELS[k] || [k, ""])[0], (TUNING_LABELS[k] || [k, ""])[1], this._tfilter));
    return html`<section class="card wide">
      <h3>Tuning <span class="muted small">applies live, no restart · distances here are metres, the solver's own unit</span></h3>
      <div class="row"><input class="tfilter" type="search" placeholder="Filter by key, label or help" aria-label="Filter tuning keys" .value=${this._tfilter} @input=${(e) => { this._tfilter = e.target.value; }}></div>
      ${groups.map(([name, keys]) => {
        const vis = shown(keys);
        if (!vis.length) return nothing;
        const chg = vis.filter((k) => tuningChanged(this._tuning[k], spec[k].default)).length;
        // Closed until asked for: eighty-odd knobs at once hid the few anyone changes. A filter opens what it matches.
        return html`<details class="tgroup" ?open=${!!this._tfilter}><summary><b>${name}</b> <span class="muted small">${vis.length} setting${vis.length === 1 ? "" : "s"}${chg ? html` · <span class="chg">${chg} changed</span>` : nothing}</span></summary><div class="row">${keys.map(field)}</div></details>`;
      })}
      <div class="row">${uiButton({ label: "Apply", kind: "primary", onClick: () => this._saveTuning() })}${uiButton({ label: "Restore defaults", kind: "text", onClick: () => this._resetTuning() })}</div>
    </section>`;
  }

  /** Try one room setting against the election log before applying it. */
  _renderReplay() {
    const spec = this.data?.tuning_spec || {};
    const keys = REPLAY_KEYS.filter((k) => spec[k]);
    const r = this._replay;
    const now = this.data?.layout?.tuning?.[this._replayKey] ?? spec[this._replayKey]?.default;
    const delta = (a, b) => html`<span class=${a < b ? "good" : a > b ? "bad" : ""}>${a} (${a > b ? "+" : ""}${a - b})</span>`;
    return html`<section class="card wide">
      <h3>Try a room setting <span class="muted small">replays the election log, changes nothing</span></h3>
      <div class="row">
        ${uiSelect({ label: "Setting", value: this._replayKey, options: keys.map((k) => ({ value: k, label: (TUNING_LABELS[k] || [k])[0] })), onChange: (v) => { this._replayKey = v; this._replay = null; }, style: "min-width: 240px" })}
        ${uiField({ label: `Value to try (now ${now ?? "default"})`, value: this._replayValue, onChange: (v) => { this._replayValue = v; }, style: "width: 180px" })}
        ${uiSelect({ label: "Window", value: this._replayHours, options: [1, 3, 6, 12, 24, 48].map((h) => ({ value: h, label: `${h} h` })), onChange: (v) => { this._replayHours = Number(v); }, style: "min-width: 110px" })}
        ${uiButton({ label: this._busy === "replay" ? "Replaying…" : "Replay", kind: "primary", disabled: !!this._busy, onClick: () => this._runReplay() })}
      </div>
      ${r ? html`<div class="wrap"><table>
        <tr><th></th><th class="num">Room switches</th><th class="num">Bounces</th></tr>
        <tr><td>As it is now</td><td class="num">${r.base.switches}</td><td class="num">${r.base.bounces}</td></tr>
        <tr><td><code>${r.key}</code> = ${r.value}</td><td class="num">${delta(r.trial.switches, r.base.switches)}</td><td class="num">${delta(r.trial.bounces, r.base.bounces)}</td></tr>
        ${Object.entries(r.things_changed || {}).map(([e, v]) => html`<tr><td style="padding-left: 22px" class="muted">${thingName(this.data, e)}</td><td class="num">${delta(v.trial.switches, v.base.switches)}</td><td class="num">${delta(v.trial.bounces, v.base.bounces)}</td></tr>`)}
      </table></div>
      <p class="small muted">${r.things} things over ${r.hours} h. A bounce is a switch undone within two minutes. The replay at today's settings matches ${fmtNum((r.base.agree ?? 0) * 100, 0)}% of what was published (${r.logged.switches} switches, ${r.logged.bounces} bounces): it is an estimate, so trust the difference more than the totals${(r.base.agree ?? 0) < 0.85 ? html`, <span class="bad">and not much at this match</span>` : nothing}.</p>` : html`<p class="small muted">Needs the election log: set <code>election_log_hours</code> above 0 under History and display and let it record first.</p>`}
    </section>`;
  }

  async _clearHistory(entity) {
    if (!(await confirmAsync(entity ? `Forget the recorded positions of ${thingName(this.data, entity)}?` : "Forget every thing's recorded positions?", { ok: "Forget", danger: true }))) return;
    const r = await callWS(this, this.hass, { type: "sextant/history/clear", ...(entity ? { entity } : {}) });
    if (r) toast(this, `History cleared (${r.removed} file${r.removed === 1 ? "" : "s"} rewritten)`);
  }

  _renderHistory() {
    const ents = this.data?.entities || [];
    return html`<section class="card">
      <h3>Position history</h3>
      <p class="small muted">The scrubber on the Live page replays these; this is only where they can be forgotten.</p>
      <div class="row">
        ${uiSelect({ label: "Thing", value: this._histEnt || "", options: [{ value: "", label: "every thing" }, ...ents.map((e) => ({ value: e, label: thingName(this.data, e) }))], onChange: (v) => { this._histEnt = v; }, style: "min-width: 220px" })}
        ${uiButton({ label: "Clear history", kind: "danger", onClick: () => this._clearHistory(this._histEnt || null) })}
      </div>
    </section>`;
  }

  static styles = [sharedStyles, widgetStyles, css`
    td.nowrap { white-space: nowrap; }
    .good { color: var(--success-color, #2e7d32); font-weight: 600; }
    .bad { color: var(--error-color, #c62828); font-weight: 600; }
    :host { display: block; overflow: auto; }
    .cols { grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); }
    .card.wide, details.fold { grid-column: 1 / -1; }
    details.fold > summary, details.tgroup > summary { cursor: pointer; padding: 8px 4px; }
    details.fold > .cols { margin-top: 8px; }
    section.receivers { grid-column: 1 / -1; }
    .attention { margin: 8px 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .group { border-top: 1px solid var(--divider-color); margin-top: 6px; }
    .grouphead { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; background: transparent; border: 0; padding: 8px 4px; font: inherit; color: inherit; cursor: pointer; border-radius: 6px; }
    .grouphead:hover { background: var(--secondary-background-color); }
    .grouphead.sub { padding-left: 28px; font-size: 13px; }
    .grouphead ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
    .room .wrap { padding-left: 28px; margin-bottom: 8px; }
    .counts { display: inline-flex; gap: 4px; }
    ul.plain { list-style: none; padding: 0; margin: 6px 0; }
    ul.plain li { padding: 3px 0; }
    details { margin-top: 8px; }
    summary { cursor: pointer; }
    h4 { margin-top: 12px; }
    /* One change plan per floor on the Advice page: a heading with the
       floor's own tally and a button that stages every one of its
       suggested spots on the map together, then that floor's own table. */
    .floorplan { border-top: 1px solid var(--divider-color); margin-top: 10px; padding-top: 8px; }
    .floorplan h4 { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
    .tfield { display: inline-flex; flex-direction: column; gap: 2px; }
    .tfield .hint { font-size: 11px; color: var(--secondary-text-color); padding-left: 2px; }
    .tfilter { box-sizing: border-box; width: 280px; max-width: 100%; padding: 8px 10px; border: 1px solid var(--divider-color); border-radius: 6px; background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
    .tfield { max-width: 260px; }
    .tfield .thelp { font-size: 11px; color: var(--secondary-text-color); padding-left: 2px; overflow-wrap: anywhere; }
    .chg { color: var(--warning-color, #f59e0b); font-weight: 600; }
    .tfield .treset { color: var(--primary-color); }
    @media (pointer: coarse) { .tfield .treset { display: inline-block; padding: 8px 6px; } }
    .ponly { display: none; }
    @media (max-width: 720px) { .ponly { display: inline; } .p-5 tr > :nth-child(5) { display: none; } .tfield { max-width: none; } .cols { grid-template-columns: 1fr; } .tfield, .tfield > * { width: 100%; } }
  `];
}

if (!customElements.get("sextant-health")) customElements.define("sextant-health", SextantHealth);
