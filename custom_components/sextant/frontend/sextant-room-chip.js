/**
 * Sextant room chip for Lovelace: who is in a room as a pill of faces, how long, and the room's mode.
 * An empty room shows how long it has been empty and who was last there.
 *
 *   type: custom:sextant-room-chip
 *   entity: binary_sensor.kitchen_sextant_occupancy
 *   max: 3                      # faces before "+N"
 *
 * Resource: /sextant/sextant-room-chip.js (module).
 *
 * Reads the room sensor named in `entity` (and its recorder history, for who was last there) and each
 * occupant's person.<slug> for the picture. Behind Strimmer the person entities are not in the card's
 * config, so the card asks for them; or list them in Strimmer's always_forward.
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { roomChip, fmtFor, lastOccupants, modeIcon, firstName, askStrimmer } from "./sextant-occupancy-data.js";
import { forwardHaContext, loadHaEditors, entityOptions } from "./sextant-ha-editors.js";

class SextantRoomChip extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true }, _last: { state: true } };

  static getConfigElement() { return document.createElement("sextant-room-chip-editor"); }

  static getStubConfig(hass) {
    return { entity: Object.keys(hass?.states || {}).find((id) => id.startsWith("binary_sensor.") && id.endsWith("_sextant_occupancy")) || "" };
  }

  setConfig(config) {
    if (!config?.entity) throw new Error("Set entity to a room's Sextant occupancy sensor");
    this._config = { max: 3, ...config };
  }

  getCardSize() { return 1; }

  connectedCallback() { super.connectedCallback(); this._tick = setInterval(() => this.requestUpdate(), 30000); }
  disconnectedCallback() { super.disconnectedCallback(); clearInterval(this._tick); }

  // hass changes many times a second; only the room's own state is drawn (faces' pictures barely change).
  shouldUpdate(changed) {
    if (!changed.has("hass") || changed.size > 1) return true;
    return changed.get("hass")?.states?.[this._config?.entity] !== this.hass?.states?.[this._config?.entity];
  }

  updated(changed) {
    // Strimmer forwards only what dashboards name; the occupants' person entities are found at runtime.
    if (changed.has("hass")) askStrimmer(this.hass?.connection);
    const r = roomChip(this.hass?.states, this._config.entity);
    // Empty: who was here last comes from the recorder, once per room and time it turned off.
    const key = r && !r.on && r.since ? `${this._config.entity}@${r.since}` : null;
    if (key && this._lastFor !== key) { this._lastFor = key; this._last = null; this._loadLast(this._config.entity, r.since, key); }
  }

  async _loadLast(entity, since, key) {
    try {
      const rows = await this.hass.callWS({
        type: "history/history_during_period", entity_ids: [entity], minimal_response: false, no_attributes: false,
        significant_changes_only: false, start_time: new Date((since - 12 * 3600) * 1000).toISOString(), end_time: new Date((since + 60) * 1000).toISOString(),
      });
      if (this._lastFor === key) this._last = lastOccupants(rows?.[entity]);
    } catch (e) {
      // Leave "last" off for now; clearing the key tries again on the next update (at most every 30 s).
      if (this._lastFor === key) { this._last = []; this._lastFor = null; }
    }
  }

  _face(f) {
    const tip = f.name;
    let src = null;
    try { src = f.picture && this.hass.hassUrl(f.picture); } catch (e) { /* a malformed picture URL: initials instead */ }
    return src ? html`<img class="face" src=${src} alt=${tip} title=${tip}>`
      : html`<span class="face ${f.pet ? "pet" : ""}" title=${tip}>${f.name.slice(0, 1).toUpperCase()}</span>`;
  }

  _key(e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this._open(); } }

  _open() { this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: this._config.entity }, bubbles: true, composed: true })); }

  render() {
    const r = roomChip(this.hass?.states, this._config.entity);
    // Missing or unavailable: not loaded yet, or a proxy (Strimmer) still reconnecting with it. Quiet, not an error.
    if (!r || this.hass.states[this._config.entity].state === "unavailable") return html`<ha-card class="chip warn"><ha-icon icon="mdi:timer-sand"></ha-icon>Waiting for ${this._config.entity}</ha-card>`;
    const age = r.since ? fmtFor(Date.now() / 1000 - r.since) : "";
    if (!r.on) {
      const last = this._last?.length ? this._last.map(firstName).join(", ") : "";
      return html`<ha-card class="chip off" role="button" tabindex="0" @click=${this._open} @keydown=${this._key} title="${r.room}: empty">
        <ha-icon icon="mdi:account-off-outline"></ha-icon><span>Empty${age ? ` · ${age}` : ""}</span>${last ? html`<span class="muted">· ${last}</span>` : nothing}</ha-card>`;
    }
    const shown = r.faces.slice(0, this._config.max), more = r.faces.length - shown.length;
    return html`<ha-card class="chip" role="button" tabindex="0" @click=${this._open} @keydown=${this._key} title="${r.room}: ${r.faces.map((f) => f.name).join(", ") || "on"}">
      ${r.faces.length ? html`<span class="faces">${shown.map((f) => this._face(f))}${more > 0 ? html`<span class="face more">+${more}</span>` : nothing}</span>`
        : html`<ha-icon icon="mdi:account-question-outline"></ha-icon>`}
      ${age ? html`<span>${age}</span>` : nothing}
      ${r.mode ? html`<ha-icon class="mode" icon=${modeIcon(r.mode)} title=${r.mode}></ha-icon>` : nothing}</ha-card>`;
  }

  static styles = css`
    :host { display: block; }
    .chip { display: inline-flex; align-items: center; gap: 8px; height: 40px; padding: 0 12px 0 6px; border-radius: 20px; font-size: 13px; cursor: pointer; max-width: 100%; white-space: nowrap; }
    .chip.off, .chip.warn { padding-left: 12px; color: var(--secondary-text-color); }
    .chip:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .chip ha-icon { --mdc-icon-size: 18px; }
    .muted { color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; margin-left: -4px; } /* "· Jack" a space after the age, not the chip's 8px gap */
    .faces { display: flex; }
    .face { width: 28px; height: 28px; border-radius: 50%; margin-left: -8px; border: 2px solid var(--ha-card-background, var(--card-background-color)); object-fit: cover;
      display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: #fff; background: var(--primary-color); box-sizing: border-box; }
    .face:first-child { margin-left: 0; }
    .face.pet { background: var(--amber-color, #ffc107); color: #000; }
    .face.more { background: var(--secondary-background-color); color: var(--secondary-text-color); font-size: 11px; }
    .mode { color: var(--amber-color, #ffc107); }
  `;
}

class SextantRoomChipEditor extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true }, _ready: { state: true } };

  constructor() { super(); forwardHaContext(this); }

  setConfig(config) { this._config = config; }

  connectedCallback() { super.connectedCallback(); loadHaEditors().then(() => { this._ready = true; }); }

  _changed(e) {
    e.stopPropagation();
    const config = { ...this._config, ...e.detail.value };
    // A cleared field goes back to the card's default rather than overriding it with nothing.
    for (const [k, v] of Object.entries(config)) if (v == null || v === "") delete config[k];
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  render() {
    if (!this.hass || !this._config) return nothing;
    if (!this._ready) return html`<div class="wait">Loading…</div>`;
    const c = this._config;
    const schema = [
      { name: "entity", required: true, selector: { select: { mode: "dropdown", options: entityOptions(this.hass.states, (id) => /^binary_sensor\..+_sextant_occupancy$/.test(id), (id, s) => s.attributes.room || id, [c.entity]) } } },
      { name: "max", selector: { number: { min: 1, max: 10, mode: "box" } } },
    ];
    return html`<ha-form .hass=${this.hass} .data=${{ entity: c.entity || "", max: c.max ?? 3 }} .schema=${schema}
      .computeLabel=${(s) => ({ entity: "Room", max: "Faces before +N" })[s.name]} @value-changed=${this._changed}></ha-form>`;
  }

  static styles = css`.wait { padding: 16px; color: var(--secondary-text-color); }`;
}

if (!customElements.get("sextant-room-chip")) customElements.define("sextant-room-chip", SextantRoomChip);
if (!customElements.get("sextant-room-chip-editor")) customElements.define("sextant-room-chip-editor", SextantRoomChipEditor);

window.customCards = window.customCards || [];
window.customCards.push({ type: "sextant-room-chip", name: "Sextant Room Chip", description: "Who is in a room, how long, and its mode, as one chip.", preview: true, documentationURL: "https://github.com/davidcoulson/sextant" });
