/** Occupancy tab: floors stacked like the house, a tile per room with who is in it and why it is on. Read only. */
import { LitElement, html, css, nothing } from "./lit.js";
import { sharedStyles, fmtAge, fmtLen, classIcon, THING_CLASSES } from "./sextant-ui.js";
import { occupancyByFloor, outsideNow, chipDetail, firstName, spotInRoom, SOURCE_ICON, SOURCE_LABEL, WHERE_SOURCE, WHERE_ICON, modeIcon } from "./sextant-occupancy-data.js";

class SextantOccupancy extends LitElement {
  static properties = { hass: {}, data: {}, _open: { state: true } };

  constructor() {
    super();
    this._open = null;          // "<floor>|<room>|<name>" of the chip whose details are showing
    this._pinned = false;       // opened by a tap or click, so leaving it with the mouse keeps it
    this.addEventListener("click", (e) => { if (!e.composedPath().some((el) => el.classList?.contains("who"))) this._close(); });
    // On the document: a hover-opened popup has no focus inside this element for Escape to reach.
    this._onKey = (e) => { if (e.key === "Escape" && this._open) this._close(); };
  }

  connectedCallback() { super.connectedCallback(); document.addEventListener("keydown", this._onKey); }
  disconnectedCallback() { super.disconnectedCallback(); document.removeEventListener("keydown", this._onKey); }

  willUpdate() {
    this._floors = occupancyByFloor(this.hass?.states, this.data?.layout?.floor);
    const out = outsideNow(this.hass?.states);
    this._outside = out.people.length || out.pets.length
      ? { name: "Outside", people: out.people.length, pets: out.pets.length, rooms: [{ room: "Outside", floor: "", on: true, peopleOn: out.people.length > 0, ids: {}, sources: [], ...out }] }
      : null;
    // The open chip's occupant left the room (or the house): drop the popup and its pin with it.
    if (this._open && ![...this._floors, ...(this._outside ? [this._outside] : [])].some((f) => f.rooms.some((r) => [...r.people, ...r.pets].some((n) => `${r.floor}|${r.room}|${n}` === this._open)))) this._close();
  }
  static styles = [sharedStyles, css`
    :host { display: block; overflow-y: auto; padding: 16px; max-width: 900px; margin: 0 auto; }
    .floor { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
    .fh { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .fh b { flex: 1; font-size: 15px; }
    .pill { font-size: 12px; padding: 2px 10px; border-radius: 8px; background: var(--secondary-background-color); color: var(--secondary-text-color); }
    .pill.on { background: color-mix(in srgb, var(--success-color, #4caf50) 20%, transparent); color: var(--primary-text-color); }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
    .room { border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px 10px; min-height: 70px; background: var(--secondary-background-color); }
    .room.on { background: color-mix(in srgb, var(--primary-color) 14%, transparent); border-color: var(--primary-color); }
    .room.pets { background: var(--secondary-background-color); border: 1px dashed var(--primary-color); }
    .room { position: relative; }
    /* Background only: the border still says occupied (solid) or pets only (dashed). */
    .room.mode { background: color-mix(in srgb, var(--accent-color, #ff9800) 18%, transparent); }
    .src .mi { --mdc-icon-size: 20px; color: var(--accent-color, #ff9800); }
    .room.mode .rn { overflow-wrap: anywhere; }
    .rn .ml { display: block; font-size: 12px; font-weight: 400; color: var(--secondary-text-color); }
    .rn { font-size: 13px; font-weight: 500; margin-bottom: 6px; }   /* its right padding is set per tile, by the icons in the corner */
    .src { position: absolute; top: 6px; right: 8px; display: flex; align-items: center; gap: 4px; color: var(--secondary-text-color); }
    .src ha-icon { --mdc-icon-size: 16px; }
    .chip { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; margin: 0 4px 4px 0; padding: 2px 7px; border-radius: 10px; background: var(--card-background-color); border: 1px solid var(--divider-color); }
    .foot { font-size: 12px; color: var(--secondary-text-color); }
    .chip ha-icon { --mdc-icon-size: 14px; }
    .who { position: relative; display: inline-block; max-width: 100%; }
    button.chip { font: inherit; font-size: 12px; color: var(--primary-text-color); cursor: pointer; text-align: start; }
    button.chip:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
    @media (pointer: coarse) { button.chip { min-height: 32px; padding: 4px 10px; } }
    /* One line: a long spot ends in an ellipsis rather than wrapping under the name (the popup has it whole). */
    button.chip { max-width: 100%; white-space: nowrap; }
    .chip .spot { color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .pop { position: absolute; z-index: 5; top: 100%; left: 0; width: max-content; max-width: min(280px, 80vw); padding: 8px 10px; border-radius: 8px;
      background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color);
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25); font-size: 12px; line-height: 1.5; }
    .pop b { display: block; font-size: 13px; margin-bottom: 2px; padding-right: 22px; }
    .pop .si { position: absolute; top: 8px; right: 8px; --mdc-icon-size: 16px; color: var(--secondary-text-color); }
    .pop .k { color: var(--secondary-text-color); margin-right: 4px; }
    /* A phone has no room beside a chip: the details sit at the bottom of the screen instead. */
    @media (max-width: 600px) { .pop { position: fixed; top: auto; left: 16px; right: 16px; bottom: 16px; max-width: none; width: auto; } }
  `];

  _close() { this._open = null; this._pinned = false; }

  _show(key, pin) {
    if (pin) {
      if (this._open === key && this._pinned) return this._close();
      this._pinned = true;
    } else if (this._pinned) return;
    if (this._open === key) return;
    this._open = key;
  }

  _chip(r, name, icon, label = name) {
    const d = chipDetail(this.hass?.states, name, r.ids, this.data?.layout?.thing_classes);
    // A person's chip shows what is tracking them (phone, watch) when that thing has a class.
    const pet = icon === "mdi:paw";   // before a person's icon becomes their device's
    if (icon === "mdi:account" && d?.thingClass) icon = classIcon(d.thingClass) || icon;
    const key = `${r.floor}|${r.room}|${name}`;
    const spot = d?.spot && d.room === r.room ? spotInRoom(d.spot, r.room, name) : null;
    return html`<span class="who"
        @pointerenter=${(e) => { if (e.pointerType === "mouse") this._show(key, false); }}
        @pointerleave=${(e) => { if (e.pointerType === "mouse" && !this._pinned && this._open === key) this._close(); }}>
      <button class="chip" aria-expanded=${this._open === key} @click=${() => this._show(key, true)}>
        <ha-icon icon=${icon}></ha-icon>${label}${spot ? html`<span class="spot">&nbsp;· ${spot}</span>` : nothing}</button>
      ${this._open === key ? this._pop(name, d, pet) : nothing}
    </span>`;
  }

  _pop(name, d, pet = false) {
    if (!d) return html`<div class="pop" role="tooltip"><b>${name}</b>No Sextant location sensor found.</div>`;
    const row = (k, v) => (v == null || v === "" ? nothing : html`<div><span class="k">${k}</span>${v}</div>`);
    const age = d.heardAt ? fmtAge((Date.now() - d.heardAt) / 1000) + " ago" : null;
    // A pet is its own tag: "Tracked by Cat" says nothing.
    const device = pet ? null : d.thing ? (THING_CLASSES.find(([k]) => k && k === d.thingClass) || [])[1] || d.thing : d.tracker;
    let src = WHERE_SOURCE[d.source] || d.source;
    if (d.source === "wifi" && d.accessPoint) src += ` (${d.accessPoint})`;
    if (d.source === "gps" && d.gpsAccuracy != null) src += ` (±${fmtLen(d.gpsAccuracy, this.hass, 0)})`;
    // The stay-lifted figure, with the single fit's own beside it when they differ.
    const pct = (x) => `${Math.round(x * 100)}%`;
    const conf = d.conf == null ? null : d.settled == null || pct(d.settled) === pct(d.conf) ? pct(d.conf) : `${pct(d.settled)} (fit ${pct(d.conf)})`;
    return html`<div class="pop" role="tooltip"><b>${name}</b>
      ${d.source ? html`<ha-icon class="si" icon=${WHERE_ICON[d.source] || "mdi:help-circle-outline"} title=${src}></ha-icon>` : nothing}
      ${d.outside ? row("Where", "Outside") : html`
        ${row("Room", d.room && d.room !== "unknown" ? d.room : "Unknown")}
        ${row("Spot", d.spot)}
        ${row("Floor", d.floor && d.floor !== "unknown" ? d.floor : null)}`}
      ${row(d.outside ? "Out for" : "Here for", d.since ? fmtAge((Date.now() - d.since) / 1000) : null)}
      ${row("Tracked by", device)}
      ${row("Confidence", conf)}
      ${row("Last heard", age ? `${age}${d.presence ? ` (${d.presence})` : ""}` : d.presence)}
    </div>`;
  }

  render() {
    const floors = this._floors || [];
    if (!floors.length && !this._outside) return html`<div class="empty">No room sensors yet. Draw rooms in Edit.</div>`;
    const people = new Set(floors.flatMap((f) => f.rooms.flatMap((r) => r.people))).size;
    return html`${[...floors, ...(this._outside ? [this._outside] : [])].map((f) => html`
      <div class="floor">
        <div class="fh"><b>${f.name}</b>
          <span class="pill ${f.people ? "on" : ""}">${f.people} ${f.people === 1 ? "person" : "people"}</span>
          ${f.pets ? html`<span class="pill">${f.pets} ${f.pets === 1 ? "pet" : "pets"}</span>` : nothing}</div>
        <div class="grid">${f.rooms.map((r) => html`
          <div class="room ${r.on ? (r.peopleOn ? "on" : "pets") : ""} ${r.mode ? "mode" : ""}">
            ${f === this._outside ? nothing : html`<div class="rn" style="padding-right:${(r.on ? r.sources.length : 0) * 20 + (r.mode ? 24 : 0) + 4}px">${r.room}${r.mode ? html`<span class="ml">${r.mode}</span>` : nothing}</div>`}
            ${r.people.map((p) => this._chip(r, p, "mdi:account", firstName(p)))}
            ${r.pets.map((p) => this._chip(r, p, "mdi:paw"))}
            ${r.mode || (r.on && r.sources.length) ? html`<div class="src">${r.on ? r.sources.map((x) => html`<ha-icon icon=${SOURCE_ICON[x] || "mdi:help-circle-outline"} title=${SOURCE_LABEL[x] || x}></ha-icon>`) : nothing}${r.mode ? html`<ha-icon class="mi" icon=${modeIcon(r.mode)} aria-hidden="true"></ha-icon>` : nothing}</div>` : nothing}
          </div>`)}</div>
      </div>`)}
      <div class="foot">${people} ${people === 1 ? "person" : "people"} in the house</div>`;
  }
}
if (!customElements.get("sextant-occupancy")) customElements.define("sextant-occupancy", SextantOccupancy);
