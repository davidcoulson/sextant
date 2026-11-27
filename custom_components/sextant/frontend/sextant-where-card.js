/**
 * Sextant "where is everyone" card for Lovelace.
 *
 *   type: custom:sextant-where-card
 *   layout: tiles                # tiles | rooms | strip | rings | pets
 *   columns: 2                   # tiles (2), rings (4) and pets' tiles (2)
 *   show_floor: true             # optional: the floor when there is no spot (tiles, rings, rooms)
 *   precise: true                # optional: one line, the spot, else room, else floor, else Home (tiles, rings, strip)
 *   entities:
 *     - entity: sensor.david_coulson_sextant_person_location
 *       person: person.david_coulson   # photo and name (optional)
 *       name: David                    # optional
 *       activity: sensor.davids_iphone_activity           # optional: "Driving near …" when away
 *       place: sensor.davids_iphone_geocoded_location     # optional: the town when away
 *       # either key may instead name a Life360 tracker (device_tracker.*): its driving flag, its place or address
 *     - sensor.meg_sextant_pet_location
 *   # pets: the pets only; each dog gets a card of its own (inside, outside or away). People listed
 *   # are not drawn: a pet in a room with one of them shows their face and "with David".
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
import { whereRows, groupRooms, stripChips, fmtStay, normEntry, withPerson, preciseWhere, petCompany, joinNames, fmtDistance } from "./sextant-where.js";
import { forwardHaContext, loadHaEditors, entityOptions } from "./sextant-ha-editors.js";

const MODE_ICONS = { sleep: "mdi:sleep", tv: "mdi:television", cooking: "mdi:chef-hat", gaming: "mdi:controller" };
const SOURCE_ICONS = { ble: "mdi:bluetooth", wifi: "mdi:wifi", gps: "mdi:map-marker-radius" };
const LAYOUTS = ["tiles", "rooms", "strip", "rings", "pets"];
const SOURCE_NAMES = { ble: "Bluetooth", wifi: "Wi-Fi", gps: "GPS", held: "Last heard" };

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
    if (this._config?.layout === "pets") {
      const rows = this.hass ? whereRows(this.hass.states, this._config.entities, Date.now() / 1000).filter((r) => r.pet) : [];
      const dogs = rows.filter((r) => r.roams).length;
      return dogs * 2 + Math.ceil((this.hass ? rows.length - dogs : n) / (this._config.columns || 2)) * 1.3;
    }
    return { tiles: Math.ceil(n / (this._config.columns || 2)) * 1.4, rooms: n, strip: 1, rings: 3 }[this._config?.layout] || 3;
  }

  // Stays are drawn as "42m": redraw each minute even when no state changes.
  connectedCallback() { super.connectedCallback(); this._timer = setInterval(() => { this._tick = Date.now(); }, 60000); }
  disconnectedCallback() { super.disconnectedCallback(); clearInterval(this._timer); }

  _more(id) { this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: id }, bubbles: true, composed: true })); }

  _avatar(r, size = "", badge = false) {
    const fallback = r.pet ? html`<ha-icon icon=${classIcon(r.via) || "mdi:paw"}></ha-icon>` : r.name[0];
    const badgeIcon = r.moving?.icon || (r.away ? SOURCE_ICONS[r.source] || "mdi:home-export-outline" : classIcon(r.via));
    // As on the house's Mushroom person cards: green home, blue in a named zone, orange on the move, red away.
    const bc = !r.away ? "" : r.zone ? "var(--blue-color, #2196f3)" : r.moving ? "var(--orange-color, #ff9800)" : "var(--red-color, #f44336)";
    // Away has no confidence: a full ring in the badge colour.
    const ring = r.level ? `--c:${r.level.color};--p:${Math.round(r.conf * 100)}` : bc ? `--c:${bc};--p:100` : "--c:var(--divider-color);--p:0";
    return html`<span class="ring ${size}" style=${ring} title=${r.level ? `${r.level.label} ${Math.round(r.conf * 100)}%` : ""}>
      <span class="av">${r.picture ? html`<img src=${r.picture} alt="">` : fallback}</span>
      ${badge && badgeIcon ? html`<span class="badge" style=${bc ? `background:${bc}` : ""}><ha-icon icon=${badgeIcon}></ha-icon></span>` : nothing}</span>`;
  }

  // The headline: where they are, or with precise only the most precise place. On the move with a
  // town, only the town (split): the badge already shows the activity.
  _where(r, split = true) {
    if (r.away) return split && r.moving && r.place ? r.place : r.where;
    return this._config.precise ? preciseWhere(r) : r.where;
  }
  // The line under it: the spot, else the floor when show_floor is on; none with precise, and none
  // away, where the place takes both lines (a long address) and the badge shows the activity.
  _sub(r) {
    if (r.away) return "";
    return this._config.precise ? "" : r.spot || (this._config.show_floor ? r.floor : null) || "";
  }

  _tiles(rows) {
    const sub = (r) => this._sub(r);
    return html`<div class="tiles" style="--cols:${this._config.columns || 2}">${rows.map((r) => html`
      <button class="tile" @click=${() => this._more(r.id)}>${this._avatar(r, "", true)}
        <span class="txt"><span class="n"><span class="nm">${r.name}</span><span class="stay">${fmtStay(r.stay, true)}</span></span>
        <span class="room ${sub(r) ? "" : "two"}" title=${this._where(r, false)}>${this._where(r)}</span>
        ${sub(r) ? html`<span class="sub" title=${sub(r)}>${sub(r)}</span>` : nothing}</span></button>`)}</div>`;
  }

  _rooms(rows) {
    const rooms = groupRooms(rows, (this._config.rooms || []).map((id) => this.hass.states[id]));
    return html`<div>${rooms.map((g) => html`<div class="rrow">
      <span class="stack">${g.rows.slice(0, 4).map((r) => this._avatar(r, "sm"))}</span>
      <span class="rbody"><span class="rtitle">${g.room}<span class="fl">${this._config.show_floor ? g.floor || "" : ""}</span>
        ${g.mode ? html`<span class="fact"><ha-icon icon=${MODE_ICONS[String(g.mode).toLowerCase()] || "mdi:home-variant-outline"}></ha-icon>${g.mode}</span>` : nothing}</span>
      <span class="who">${g.rows.map((r) => html`<button class="link" @click=${() => this._more(r.id)}><b>${r.name}</b>${r.spot ? ` at ${r.spot}` : ""} ${fmtStay(r.stay, true)}</button>`)}</span></span></div>`)}</div>`;
  }

  _strip(rows) {
    return html`<div class="strip">${stripChips(rows).map((c) => c.kind === "one"
      ? html`<button class="chip" @click=${() => this._more(c.row.id)}>${this._avatar(c.row, "xs")}${c.row.name} · ${this._where(c.row, false)}<span class="stay">${fmtStay(c.row.stay, true)}</span></button>`
      : html`<span class="chip" title=${c.rows.map((r) => `${r.name}: ${r.spot || r.where}`).join("\n")}><span class="stack">${c.rows.map((r) => this._avatar(r, "xs"))}</span>${c.rows.length} ${c.cls}s · ${c.floor || "?"}</span>`)}</div>`;
  }

  _rings(rows) {
    const people = rows.filter((r) => !r.pet), pets = rows.filter((r) => r.pet);
    return html`<div><div class="rings" style="--cols:${this._config.columns || 4}">${people.map((r) => html`
      <button class="cell" @click=${() => this._more(r.id)}>${this._avatar(r, "lg", true)}${r.stay != null ? html`<span class="t">${fmtStay(r.stay, true)}</span>` : nothing}
        <span class="n">${r.name}</span><span class="room ${this._sub(r) ? "" : "two"}" title=${this._where(r, false)}>${this._where(r)}</span>
        ${this._sub(r) ? html`<span class="sub">${this._sub(r)}</span>` : nothing}</button>`)}</div>
      ${pets.length ? html`<div class="pets">${pets.map((r) => html`<button class="pet" @click=${() => this._more(r.id)}>${this._avatar(r, "xs")}${r.name} <span class="sub">${this._config.precise ? preciseWhere(r) : r.spot || r.where}</span></button>`)}</div>` : nothing}</div>`;
  }

  // Pets: each dog a card (inside, outside or away; where; trackers), the rest as tiles. A person in the same
  // room puts their face on the pet's photo and "with David" under it; people themselves are not drawn.
  _pets(rows) {
    const company = petCompany(rows), pets = rows.filter((r) => r.pet);
    const dogs = pets.filter((r) => r.roams), rest = pets.filter((r) => !r.roams);
    const face = (r, size) => {
      const w = company.get(r.id) || [];
      return html`<span class="pface">${this._avatar(r, size)}${w[0] ? html`<span class="with-face" title=${w[0].name}>
        ${w[0].picture ? html`<img src=${w[0].picture} alt="">` : w[0].name[0]}</span>` : nothing}</span>`;
    };
    const withChip = (r) => {
      const w = company.get(r.id) || [];
      return w.length ? html`<span class="with">with ${joinNames(w.map((x) => x.name))}</span>` : nothing;
    };
    const where = (r) => r.away ? this._where(r) : r.spot || r.where;
    const dog = (r) => {
      const state = r.where === "Unavailable" ? null : r.away ? "away" : r.outside ? "outside" : "inside";
      const how = [SOURCE_NAMES[r.source], r.distance != null ? `${fmtDistance(r.distance)} from home` : ""].filter(Boolean).join(" · ");
      return html`<button class="dog" @click=${() => this._more(r.id)}>${face(r, "xl")}
        <span class="txt"><span class="n">${r.name}</span>
          <span class="states">${["inside", "outside", "away"].map((s) => html`<span class="st ${s === state ? `on ${s}` : ""}">${s[0].toUpperCase() + s.slice(1)}</span>`)}</span>
          <span class="room ${r.away ? "two" : ""}" title=${this._where(r, false)}>${where(r)}${r.stay != null ? html` <span class="stay">· ${fmtStay(r.stay, true)}</span>` : nothing}</span>
          ${withChip(r)}${how ? html`<span class="sub">${how}</span>` : nothing}</span></button>`;
    };
    return html`${dogs.map(dog)}${rest.length ? html`<div class="ptiles ${dogs.length ? "below" : ""}" style="--cols:${this._config.columns || 2}">${rest.map((r) => html`
      <button class="ptile" @click=${() => this._more(r.id)}>${face(r, "")}
        <span class="txt"><span class="n"><span class="nm">${r.name}</span><span class="stay">${fmtStay(r.stay, true)}</span></span>
          <span class="room ${r.away ? "two" : ""}" title=${this._where(r, false)}>${where(r)}</span>${withChip(r)}</span></button>`)}</div>` : nothing}`;
  }

  render() {
    if (!this._config || !this.hass) return nothing;
    const rows = whereRows(this.hass.states, this._config.entities, Date.now() / 1000);
    const body = { tiles: this._tiles, rooms: this._rooms, strip: this._strip, rings: this._rings, pets: this._pets }[this._config.layout].call(this, rows);
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
    .badge ha-icon { display: flex; } /* inline ha-icon sits on the text baseline, off centre */
    .stack { display: flex; flex: none; } .stack .ring + .ring { margin-left: -9px; }
    .fact { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px 1px 6px; border-radius: 999px; font-size: 12px; font-weight: 400;
      color: color-mix(in srgb, var(--purple-color, #926bc7) 40%, var(--primary-text-color)); background: color-mix(in srgb, var(--purple-color, #926bc7) 16%, transparent); --mdc-icon-size: 14px; }
    .fact ha-icon { color: var(--purple-color, #926bc7); }

    .tiles { display: grid; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)); gap: 8px; }
    .tile { display: flex; gap: 10px; align-items: center; min-width: 0; overflow: hidden; padding: 6px 10px; border-radius: var(--ha-card-border-radius, 12px);
      background: var(--ha-card-background, var(--card-background-color)); border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color)); }
    .tile .txt { display: flex; flex-direction: column; min-width: 0; flex: 1; line-height: 1.2; }
    /* No line under it (away, or precise): a long place, "Valley Parkway Connector, Ohio", gets both lines. */
    .room.two { white-space: normal; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
    .tile .n { font-weight: 600; display: flex; gap: 6px; align-items: baseline; }
    .tile .nm { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tile .stay { margin-left: auto; flex: none; font-weight: 400; font-size: 11px; }
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

    .ring.xl { --s: 60px; }
    .pface { position: relative; flex: none; display: inline-grid; }
    .with-face { position: absolute; right: -5px; bottom: -5px; width: 22px; height: 22px; border-radius: 50%; overflow: hidden; display: grid; place-items: center;
      font-size: 11px; font-weight: 600; background: var(--secondary-background-color); border: 2px solid var(--card-background-color, var(--ha-card-background)); }
    .ring.xl + .with-face { width: 28px; height: 28px; }
    .with-face img { width: 100%; height: 100%; object-fit: cover; }
    .with { align-self: flex-start; margin-top: 3px; padding: 1px 8px; border-radius: 999px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;
      color: color-mix(in srgb, var(--blue-color, #2196f3) 45%, var(--primary-text-color)); background: color-mix(in srgb, var(--blue-color, #2196f3) 15%, transparent); }
    .dog { display: flex; gap: 14px; align-items: center; width: 100%; min-width: 0; }
    .dog + .dog { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--divider-color); }
    .dog .txt, .ptile .txt { display: flex; flex-direction: column; min-width: 0; flex: 1; line-height: 1.25; }
    .dog .n { font-weight: 600; font-size: 17px; }
    .dog .room { font-size: 15px; } .dog .sub { font-size: 12px; margin-top: 2px; }
    .states { display: flex; gap: 4px; margin: 4px 0; }
    .st { font-size: 12px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--divider-color); color: var(--secondary-text-color); }
    .st.on { border-color: transparent; color: #fff; } .st.inside { background: var(--green-color, #4caf50); }
    .st.outside { background: var(--amber-color, #ffc107); color: #000; } .st.away { background: var(--red-color, #f44336); }
    .ptiles { display: grid; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)); gap: 12px 8px; }
    .ptiles.below { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--divider-color); }
    .ptile { display: flex; gap: 10px; align-items: center; min-width: 0; }
    .ptile .n { font-weight: 600; display: flex; gap: 6px; align-items: baseline; }
    .ptile .nm { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ptile .stay { margin-left: auto; flex: none; font-weight: 400; font-size: 11px; }

    /* No color-mix (Safari before 16.4): plain rings and chips. */
    @supports not (color: color-mix(in srgb, red, blue)) { .ring { background: var(--c); } .with { background: var(--secondary-background-color); color: var(--primary-text-color); } .fact { background: var(--secondary-background-color); color: var(--primary-text-color); } }
  `;
}

const WHERE_LABELS = {
  layout: "Layout",
  entities: "People and pets",
  rooms: "Rooms whose mode to show (rooms layout)",
  show_floor: "Show the floor",
  precise: "Only the most precise place (spot, room, floor, home)",
};

class SextantWhereCardEditor extends LitElement {
  static properties = { hass: { attribute: false }, _config: { state: true }, _ready: { state: true } };

  constructor() { super(); forwardHaContext(this); }

  setConfig(config) { this._config = config; }

  connectedCallback() { super.connectedCallback(); loadHaEditors().then(() => { this._ready = true; }); }

  _changed(e) {
    e.stopPropagation();
    const v = e.detail.value;
    // A sensor already listed keeps its entry (name, person); a new one gets its person when there is one.
    // Entries queued per sensor, so a sensor listed twice keeps both of its entries.
    const had = new Map();
    for (const x of this._config.entities || []) { const id = normEntry(x).entity; had.set(id, [...(had.get(id) || []), x]); }
    const entities = (v.entities || []).flatMap((id) => had.get(id)?.splice(0) ?? [withPerson(this.hass.states, id, this.hass.entities)]);
    const config = { ...this._config, layout: v.layout || "tiles", entities };
    for (const k of ["columns", "rooms", "show_floor", "precise"]) { if (v[k] == null || v[k] === false || (Array.isArray(v[k]) && !v[k].length)) delete config[k]; else config[k] = v[k]; }
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
      { name: "entities", selector: { select: { multiple: true, reorder: true, mode: "dropdown", options: entityOptions(states, (id) => /^sensor\..+_sextant_(person|pet)_location$/.test(id), (id, s) => (s.attributes.friendly_name || id).replace(/ Location$/, ""), ids) } } },
      ...(["tiles", "rings", "pets"].includes(layout) ? [{ name: "columns", selector: { number: { min: 1, max: 6, mode: "box" } } }] : []),
      ...(layout === "rooms" || layout === "pets" ? [] : [{ name: "precise", selector: { boolean: {} } }]),
      ...(layout === "strip" || layout === "pets" || (c.precise && layout !== "rooms") ? [] : [{ name: "show_floor", selector: { boolean: {} } }]),
      ...(layout === "rooms" ? [{ name: "rooms", selector: { select: { multiple: true, mode: "dropdown", options: entityOptions(states, (id) => /^binary_sensor\..+_sextant_occupancy$/.test(id), (id, s) => s.attributes.room || id, c.rooms || []) } } }] : []),
    ];
    const data = { layout, entities: ids, columns: c.columns, rooms: c.rooms || [], show_floor: !!c.show_floor, precise: !!c.precise };
    return html`<ha-form .hass=${this.hass} .data=${data} .schema=${schema} .computeLabel=${(s) => s.name === "columns" ? `Columns (blank: ${layout === "rings" ? 4 : 2})` : WHERE_LABELS[s.name] || s.name} @value-changed=${this._changed}></ha-form>
      ${layout === "pets" ? html`<p class="hint">Pets layout: people listed here are not drawn; a pet in the same room as one shows "with" them.</p>` : nothing}
      <p class="hint">Names and photos come from each person; set <code>name</code> or <code>person</code> on an entry in YAML to change them.</p>`;
  }

  static styles = css`.hint { color: var(--secondary-text-color); font-size: 13px; } .wait { padding: 16px; color: var(--secondary-text-color); }`;
}

if (!customElements.get("sextant-where-card")) customElements.define("sextant-where-card", SextantWhereCard);
if (!customElements.get("sextant-where-card-editor")) customElements.define("sextant-where-card-editor", SextantWhereCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "sextant-where-card", name: "Sextant Where", description: "Where everyone is: room, spot, floor, time there and how sure.", documentationURL: "https://github.com/davidcoulson/sextant" });
