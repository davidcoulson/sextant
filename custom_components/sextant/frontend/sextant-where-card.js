/**
 * Sextant "where is everyone" card for Lovelace.
 *
 *   type: custom:sextant-where-card
 *   layout: tiles                # tiles | rooms | strip | rings
 *   columns: 2                   # tiles and rings
 *   entities:
 *     - entity: sensor.david_coulson_sextant_person_location
 *       person: person.david_coulson   # photo and name (optional)
 *       name: David                    # optional
 *     - sensor.meg_sextant_pet_location
 *   rooms:                       # optional: room occupancy sensors, for modes (rooms layout)
 *     - binary_sensor.great_room_sextant_occupancy
 *
 * Every entity the card reads is named in its config and read from
 * hass.states only (no websocket calls, no registries), so it works behind
 * Strimmer, which forwards a dashboard just the entity ids its config names.
 *
 * Resource: /sextant/sextant-where-card.js (module).
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { classIcon } from "./sextant-ui.js";
import { whereRows, groupRooms, stripChips, fmtStay, normEntry, withPerson } from "./sextant-where.js";
import { loadHaEditors, entityOptions } from "./sextant-ha-editors.js";

const MODE_ICONS = { sleep: "mdi:sleep", tv: "mdi:television", cooking: "mdi:chef-hat", gaming: "mdi:controller" };
const SOURCE_ICONS = { ble: "mdi:bluetooth", wifi: "mdi:wifi", gps: "mdi:map-marker-radius" };
const LAYOUTS = ["tiles", "rooms", "strip", "rings"];

class SextantWhereCard extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true }, _tick: { state: true } };

  static getConfigElement() { return document.createElement("sextant-where-card-editor"); }

  static getStubConfig(hass) {
    const ids = Object.keys(hass?.states || {}).filter((id) => /_sextant_(person|pet)_location$/.test(id));
    return { layout: "tiles", entities: ids };
  }

  setConfig(config) {
    if (!Array.isArray(config?.entities) || !config.entities.length) throw new Error("entities: list the Sextant location sensors to show");
    if (config.layout && !LAYOUTS.includes(config.layout)) throw new Error(`layout: one of ${LAYOUTS.join(", ")}`);
    this._config = { layout: "tiles", ...config };
  }

  getCardSize() {
    const n = this._config?.entities?.length || 1;
    return { tiles: Math.ceil(n / (this._config.columns || 2)) * 1.5, rooms: n, strip: 1, rings: 3 }[this._config?.layout] || 3;
  }

  // Stays are drawn as "42m": redraw each minute even when no state changes.
  connectedCallback() { super.connectedCallback(); this._timer = setInterval(() => { this._tick = Date.now(); }, 60000); }
  disconnectedCallback() { super.disconnectedCallback(); clearInterval(this._timer); }

  _more(id) { this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: id }, bubbles: true, composed: true })); }

  _avatar(r, size = "", badge = false) {
    const ring = r.level ? `--c:${r.level.color};--p:${Math.round(r.conf * 100)}` : "--c:var(--divider-color);--p:0";
    const fallback = r.pet ? html`<ha-icon icon=${classIcon(r.via) || "mdi:paw"}></ha-icon>` : r.name[0];
    const badgeIcon = r.away ? SOURCE_ICONS[r.source] : classIcon(r.via);
    return html`<span class="ring ${size}" style=${ring} title=${r.level ? `${r.level.label} ${Math.round(r.conf * 100)}%` : ""}>
      <span class="av">${r.picture ? html`<img src=${r.picture} alt="">` : fallback}</span>
      ${badge && badgeIcon ? html`<span class="badge"><ha-icon icon=${badgeIcon}></ha-icon></span>` : nothing}</span>`;
  }

  _tiles(rows) {
    return html`<div class="tiles" style="--cols:${this._config.columns || 2}">${rows.map((r) => html`
      <button class="tile" @click=${() => this._more(r.id)}>${this._avatar(r, "", true)}
        <span class="txt"><span class="n">${r.name}<span class="stay">${fmtStay(r.stay, true)}</span></span>
        <span class="room">${r.where}</span><span class="sub">${r.spot || r.floor || ""}</span></span></button>`)}</div>`;
  }

  _rooms(rows) {
    const rooms = groupRooms(rows, (this._config.rooms || []).map((id) => this.hass.states[id]));
    return html`<div>${rooms.map((g) => html`<div class="rrow">
      <span class="stack">${g.rows.slice(0, 4).map((r) => this._avatar(r, "sm"))}</span>
      <span class="rbody"><span class="rtitle">${g.room}<span class="fl">${g.floor || ""}</span>
        ${g.mode ? html`<span class="fact"><ha-icon icon=${MODE_ICONS[String(g.mode).toLowerCase()] || "mdi:home-variant-outline"}></ha-icon>${g.mode}</span>` : nothing}</span>
      <span class="who">${g.rows.map((r) => html`<button class="link" @click=${() => this._more(r.id)}><b>${r.name}</b>${r.spot ? ` at ${r.spot}` : ""} ${fmtStay(r.stay, true)}</button>`)}</span></span></div>`)}</div>`;
  }

  _strip(rows) {
    return html`<div class="strip">${stripChips(rows).map((c) => c.kind === "one"
      ? html`<button class="chip" @click=${() => this._more(c.row.id)}>${this._avatar(c.row, "xs")}${c.row.name} · ${c.row.where}<span class="stay">${fmtStay(c.row.stay, true)}</span></button>`
      : html`<span class="chip" title=${c.rows.map((r) => `${r.name}: ${r.spot || r.where}`).join("\n")}><span class="stack">${c.rows.map((r) => this._avatar(r, "xs"))}</span>${c.rows.length} ${c.cls}s · ${c.floor || "?"}</span>`)}</div>`;
  }

  _rings(rows) {
    const people = rows.filter((r) => !r.pet), pets = rows.filter((r) => r.pet);
    return html`<div><div class="rings" style="--cols:${this._config.columns || 4}">${people.map((r) => html`
      <button class="cell" @click=${() => this._more(r.id)}>${this._avatar(r, "lg", true)}${r.stay != null ? html`<span class="t">${fmtStay(r.stay, true)}</span>` : nothing}
        <span class="n">${r.name}</span><span class="room">${r.where}</span><span class="sub">${r.spot || r.floor || ""}</span></button>`)}</div>
      ${pets.length ? html`<div class="pets">${pets.map((r) => html`<button class="pet" @click=${() => this._more(r.id)}>${this._avatar(r, "xs")}${r.name} <span class="sub">${r.spot || r.where}</span></button>`)}</div>` : nothing}</div>`;
  }

  render() {
    if (!this._config || !this.hass) return nothing;
    const rows = whereRows(this.hass.states, this._config.entities, Date.now() / 1000);
    const body = { tiles: this._tiles, rooms: this._rooms, strip: this._strip, rings: this._rings }[this._config.layout].call(this, rows);
    // tiles and strip sit straight on the dashboard like the tile and chips cards; the others get a card.
    return ["tiles", "strip"].includes(this._config.layout) ? body : html`<ha-card>${body}</ha-card>`;
  }

  static styles = css`
    :host { display: block; }
    ha-card { padding: 12px; }
    button { font: inherit; color: inherit; background: none; border: 0; padding: 0; text-align: start; cursor: pointer; }
    button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; border-radius: 8px; }
    .sub, .stay, .fl { color: var(--secondary-text-color); }
    .room, .sub, .who { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    .ring { position: relative; flex: none; display: inline-grid; padding: 3px; border-radius: 50%;
      background: conic-gradient(var(--c) calc(var(--p) * 1%), color-mix(in srgb, var(--c) 18%, transparent) 0); --s: 40px; }
    .ring.lg { --s: 50px; } .ring.sm { --s: 28px; padding: 2px; } .ring.xs { --s: 20px; padding: 2px; }
    .av { width: var(--s); height: var(--s); border-radius: 50%; overflow: hidden; display: grid; place-items: center;
      background: var(--secondary-background-color); border: 2px solid var(--card-background-color, var(--ha-card-background));
      font-weight: 600; font-size: calc(var(--s) * .4); --mdc-icon-size: calc(var(--s) * .6); }
    .av img { width: 100%; height: 100%; object-fit: cover; }
    .badge { position: absolute; right: -3px; top: -3px; width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center;
      background: var(--green-color, #4caf50); color: #fff; border: 2px solid var(--card-background-color, var(--ha-card-background)); --mdc-icon-size: 12px; }
    .stack { display: flex; flex: none; } .stack .ring + .ring { margin-left: -9px; }
    .fact { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px 1px 6px; border-radius: 999px; font-size: 12px; font-weight: 400;
      color: color-mix(in srgb, var(--purple-color, #926bc7) 40%, var(--primary-text-color)); background: color-mix(in srgb, var(--purple-color, #926bc7) 16%, transparent); --mdc-icon-size: 14px; }
    .fact ha-icon { color: var(--purple-color, #926bc7); }

    .tiles { display: grid; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)); gap: 8px; }
    .tile { display: flex; gap: 10px; align-items: center; min-width: 0; padding: 8px 10px; border-radius: var(--ha-card-border-radius, 12px);
      background: var(--ha-card-background, var(--card-background-color)); border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color)); }
    .tile .txt { display: flex; flex-direction: column; min-width: 0; flex: 1; }
    .tile .n { font-weight: 600; display: flex; gap: 6px; align-items: baseline; }
    .tile .stay { margin-left: auto; font-weight: 400; font-size: 11px; }
    .tile .sub { font-size: 12px; }

    .rrow { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-top: 1px solid var(--divider-color); }
    .rrow:first-child { border-top: 0; padding-top: 0; } .rrow:last-child { padding-bottom: 0; }
    .rrow .stack { width: 84px; }
    .rbody { display: flex; flex-direction: column; min-width: 0; flex: 1; }
    .rtitle { display: flex; gap: 6px; align-items: center; font-weight: 600; }
    .rtitle .fl { font-weight: 400; font-size: 12px; } .rtitle .fact { margin-left: auto; }
    .who { font-size: 12px; color: var(--secondary-text-color); }
    .who b { color: var(--primary-text-color); font-weight: 500; }
    .who .link + .link::before { content: " · "; }

    .strip { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px 2px 2px; border-radius: 999px; font-size: 13px; white-space: nowrap;
      background: var(--ha-card-background, var(--card-background-color)); border: 1px solid var(--divider-color); }
    .chip .stack .ring + .ring { margin-left: -7px; }
    .chip .stay { font-size: 11px; }

    .rings { display: grid; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)); gap: 10px 4px; }
    .cell { position: relative; display: flex; flex-direction: column; align-items: center; min-width: 0; text-align: center; }
    .cell .t { position: absolute; top: 47px; left: 50%; transform: translateX(-50%); font-size: 10px; padding: 0 5px; border-radius: 999px;
      background: var(--secondary-background-color); border: 1px solid var(--divider-color); }
    .cell .n { font-weight: 600; font-size: 13px; margin-top: 7px; }
    .cell .room, .cell .sub { font-size: 12px; max-width: 100%; } .cell .sub { font-size: 11px; }
    .pets { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--divider-color); font-size: 12px; }
    .pet { display: inline-flex; gap: 4px; align-items: center; white-space: nowrap; }

    /* No color-mix (Safari before 16.4): plain rings and chips. */
    @supports not (color: color-mix(in srgb, red, blue)) { .ring { background: var(--c); } .fact { background: var(--secondary-background-color); color: var(--primary-text-color); } }
  `;
}

const WHERE_LABELS = {
  layout: "Layout",
  entities: "People and pets",
  columns: "Columns (blank: 2)",
  rooms: "Rooms whose mode to show (rooms layout)",
};

class SextantWhereCardEditor extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true }, _ready: { state: true } };

  setConfig(config) { this._config = config; }

  connectedCallback() { super.connectedCallback(); loadHaEditors().then(() => { this._ready = true; }); }

  _changed(e) {
    e.stopPropagation();
    const v = e.detail.value;
    // A sensor already listed keeps its entry (name, person); a new one gets its person when there is one.
    const had = new Map((this._config.entities || []).map((x) => [normEntry(x).entity, x]));
    const config = { ...this._config, layout: v.layout || "tiles", entities: (v.entities || []).map((id) => had.get(id) ?? withPerson(this.hass.states, id)) };
    for (const k of ["columns", "rooms"]) { if (v[k] == null || (Array.isArray(v[k]) && !v[k].length)) delete config[k]; else config[k] = v[k]; }
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  render() {
    if (!this.hass || !this._config) return nothing;
    if (!this._ready) return html`<div class="wait">Loading…</div>`;
    const c = this._config, layout = c.layout || "tiles", states = this.hass.states;
    const ids = (c.entities || []).map((x) => normEntry(x).entity);
    const schema = [
      { name: "layout", selector: { select: { mode: "dropdown", options: LAYOUTS.map((l) => ({ value: l, label: l[0].toUpperCase() + l.slice(1) })) } } },
      { name: "entities", selector: { select: { multiple: true, mode: "dropdown", options: entityOptions(states, (id) => /^sensor\..+_sextant_(person|pet)_location$/.test(id), (id, s) => (s.attributes.friendly_name || id).replace(/ Location$/, ""), ids) } } },
      ...(layout === "tiles" || layout === "rings" ? [{ name: "columns", selector: { number: { min: 1, max: 6, mode: "box" } } }] : []),
      ...(layout === "rooms" ? [{ name: "rooms", selector: { select: { multiple: true, mode: "dropdown", options: entityOptions(states, (id) => /^binary_sensor\..+_sextant_occupancy$/.test(id), (id, s) => s.attributes.room || id, c.rooms || []) } } }] : []),
    ];
    const data = { layout, entities: ids, columns: c.columns, rooms: c.rooms || [] };
    return html`<ha-form .hass=${this.hass} .data=${data} .schema=${schema} .computeLabel=${(s) => WHERE_LABELS[s.name] || s.name} @value-changed=${this._changed}></ha-form>
      <p class="hint">Names and photos come from each person; set <code>name</code> or <code>person</code> on an entry in YAML to change them.</p>`;
  }

  static styles = css`.hint { color: var(--secondary-text-color); font-size: 13px; } .wait { padding: 16px; color: var(--secondary-text-color); }`;
}

if (!customElements.get("sextant-where-card")) customElements.define("sextant-where-card", SextantWhereCard);
if (!customElements.get("sextant-where-card-editor")) customElements.define("sextant-where-card-editor", SextantWhereCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "sextant-where-card", name: "Sextant Where", description: "Where everyone is: room, spot, floor, time there and how sure.", documentationURL: "https://github.com/davidcoulson/sextant" });
