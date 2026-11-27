/**
 * Sextant room chip for Lovelace: who is in a room as a pill of faces, how long, and the room's mode.
 * An empty room shows how long it has been empty and who was last there.
 *
 *   type: custom:sextant-room-chip
 *   entity: binary_sensor.kitchen_sextant_occupancy
 *   max: 3                      # faces before "+N"
 *
 * Resource: /sextant/sextant-room-chip.js (module).
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { roomChip, fmtFor, lastOccupants, modeIcon, firstName } from "./sextant-occupancy-data.js";

class SextantRoomChip extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true }, _last: { state: true } };

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

  updated() {
    const r = roomChip(this.hass?.states, this._config.entity);
    // Empty: who was here last comes from the recorder, once per time the room turns off.
    if (r && !r.on && r.since && this._lastFor !== r.since) { this._lastFor = r.since; this._last = null; this._loadLast(r.since); }
  }

  async _loadLast(since) {
    try {
      const rows = await this.hass.callWS({
        type: "history/history_during_period", entity_ids: [this._config.entity], minimal_response: false, no_attributes: false,
        significant_changes_only: false, start_time: new Date((since - 12 * 3600) * 1000).toISOString(), end_time: new Date((since + 60) * 1000).toISOString(),
      });
      if (this._lastFor === since) this._last = lastOccupants(rows?.[this._config.entity]);
    } catch (e) {
      if (this._lastFor === since) this._last = [];   // no recorder or no access: the chip just leaves "last" off
    }
  }

  _face(f) {
    const tip = f.name;
    return f.picture ? html`<img class="face" src=${this.hass.hassUrl(f.picture)} alt=${tip} title=${tip}>`
      : html`<span class="face ${f.pet ? "pet" : ""}" title=${tip}>${f.name.slice(0, 1).toUpperCase()}</span>`;
  }

  _open() { this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: this._config.entity }, bubbles: true, composed: true })); }

  render() {
    const r = roomChip(this.hass?.states, this._config.entity);
    if (!r) return html`<ha-card class="chip warn">${this._config.entity} not found</ha-card>`;
    const age = r.since ? fmtFor(Date.now() / 1000 - r.since) : "";
    if (!r.on) {
      const last = this._last?.length ? this._last.map(firstName).join(", ") : "";
      return html`<ha-card class="chip off" role="button" tabindex="0" @click=${this._open} title="${r.room}: empty">
        <ha-icon icon="mdi:account-off-outline"></ha-icon><span>Empty${age ? ` · ${age}` : ""}</span>${last ? html`<span class="muted">· ${last}</span>` : nothing}</ha-card>`;
    }
    const shown = r.faces.slice(0, this._config.max), more = r.faces.length - shown.length;
    return html`<ha-card class="chip" role="button" tabindex="0" @click=${this._open} title="${r.room}: ${r.faces.map((f) => f.name).join(", ") || "on"}">
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
    .muted { color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; }
    .faces { display: flex; }
    .face { width: 28px; height: 28px; border-radius: 50%; margin-left: -8px; border: 2px solid var(--ha-card-background, var(--card-background-color)); object-fit: cover;
      display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: #fff; background: var(--primary-color); box-sizing: border-box; }
    .face:first-child { margin-left: 0; }
    .face.pet { background: var(--amber-color, #ffc107); color: #000; }
    .face.more { background: var(--secondary-background-color); color: var(--secondary-text-color); font-size: 11px; }
    .mode { color: var(--amber-color, #ffc107); }
  `;
}

if (!customElements.get("sextant-room-chip")) customElements.define("sextant-room-chip", SextantRoomChip);

window.customCards = window.customCards || [];
window.customCards.push({ type: "sextant-room-chip", name: "Sextant Room Chip", description: "Who is in a room, how long, and its mode, as one chip.", preview: true, documentationURL: "https://github.com/davidcoulson/sextant" });
