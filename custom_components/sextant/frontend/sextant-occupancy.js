/** Occupancy tab: floors stacked like the house, a row per room with who is in it and why it is on,
 *  the empty rooms on one line. Tapping a person, pet, room or floor opens its last 24 hours. Read only. */
import { LitElement, html, css, nothing, repeat } from "./lit.js";
import { sharedStyles, fmtAge, fmtLen, classIcon, THING_CLASSES } from "./sextant-ui.js";
import { occupancyByFloor, isActive, outsideNow, chipDetail, firstName, spotInRoom, SOURCE_ICON, SOURCE_LABEL, WHERE_SOURCE, WHERE_ICON, modeIcon,
  trackedPeople, staysFromHistory, subjectHistory, clockAt } from "./sextant-occupancy-data.js";

const HISTORY_HOURS = 24;

class SextantOccupancy extends LitElement {
  static properties = { hass: {}, data: {}, _hover: { state: true }, _subject: { state: true }, _hist: { state: true } };

  constructor() {
    super();
    this._hover = null;         // "<floor>|<room>|<name>" of the chip whose details show on mouse hover
    this._subject = null;       // what the history sheet is for: {kind: "person"|"room"|"floor", ...}
    this._hist = null;          // {people: [{name, pet, stays}]} | {error} | null while loading
    // On the document: the hover popup has no focus inside this element for Escape to reach.
    this._onKey = (e) => { if (e.key !== "Escape") return; if (this._subject) this._closeHistory(); else this._hover = null; };
  }

  connectedCallback() { super.connectedCallback(); document.addEventListener("keydown", this._onKey); }
  disconnectedCallback() { super.disconnectedCallback(); document.removeEventListener("keydown", this._onKey); }

  willUpdate() {
    this._floors = occupancyByFloor(this.hass?.states, this.data?.layout?.floor);
    const out = outsideNow(this.hass?.states);
    this._outside = out.people.length || out.pets.length
      ? { name: "Outside", outside: true, people: out.people.length, pets: out.pets.length, rooms: [{ room: "Outside", floor: "", on: true, peopleOn: out.people.length > 0, ids: {}, sources: [], ...out }] }
      : null;
  }

  static styles = [sharedStyles, css`
    :host { display: block; overflow-y: auto; padding: 16px; max-width: 900px; margin: 0 auto; }
    .floor { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 12px; padding: 10px 14px; margin-bottom: 12px; }
    .fh { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .fh .fname { flex: 1; font-size: 15px; font-weight: 600; text-align: start; }
    .pill { font-size: 12px; padding: 2px 10px; border-radius: 8px; background: var(--secondary-background-color); color: var(--secondary-text-color); white-space: nowrap; }
    .pill.on { background: color-mix(in srgb, var(--success-color, #4caf50) 20%, transparent); color: var(--primary-text-color); }
    /* A name that opens its history: reads as text, works as a button. */
    button.link { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; text-align: start; }
    button.link:hover { text-decoration: underline; }
    button.link:focus-visible, button.chip:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; border-radius: 4px; }

    /* A row per room. Narrow: the name and icons on one line, the chips under them. */
    .row { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "n i" "w w"; gap: 4px 8px; padding: 8px 4px; border-top: 1px solid var(--divider-color); }
    .fh + .row { border-top: 0; }
    /* The left edge says why: solid occupied, faint pets only, orange a mode (which also tints the row). */
    .row.on { box-shadow: inset 3px 0 0 var(--primary-color); padding-left: 10px; }
    .row.pets { box-shadow: inset 3px 0 0 color-mix(in srgb, var(--primary-color) 45%, transparent); padding-left: 10px; }
    .row.mode { box-shadow: inset 3px 0 0 var(--accent-color, #ff9800); padding-left: 10px; background: color-mix(in srgb, var(--accent-color, #ff9800) 8%, transparent); }
    .rn { grid-area: n; font-size: 13px; font-weight: 500; min-width: 0; overflow-wrap: anywhere; }
    .rn .ml { color: var(--accent-color, #ff9800); font-weight: 400; font-size: 12px; margin-left: 6px; }
    .src { grid-area: i; display: flex; align-items: center; gap: 4px; color: var(--secondary-text-color); }
    .src ha-icon { --mdc-icon-size: 16px; }
    .src .mi { --mdc-icon-size: 18px; color: var(--accent-color, #ff9800); }
    .w { grid-area: w; display: flex; flex-wrap: wrap; gap: 4px; min-width: 0; }
    .since { display: none; }
    /* Wide: one line per room, with when it last turned on or off. */
    @media (min-width: 601px) {
      .row { grid-template-columns: 190px minmax(0, 1fr) auto auto; grid-template-areas: "n w t i"; align-items: center; }
      .since { display: block; grid-area: t; font-size: 12px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
    }
    .quiet { font-size: 12px; color: var(--secondary-text-color); padding: 8px 4px 2px; border-top: 1px solid var(--divider-color); }
    .fh + .quiet { border-top: 0; }

    .chip { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; padding: 2px 7px; border-radius: 10px; background: var(--card-background-color); border: 1px solid var(--divider-color); }
    .chip ha-icon { --mdc-icon-size: 14px; }
    .foot { font-size: 12px; color: var(--secondary-text-color); }
    .who { position: relative; display: inline-block; max-width: 100%; }
    button.chip { font: inherit; font-size: 12px; color: var(--primary-text-color); cursor: pointer; text-align: start; max-width: 100%; white-space: nowrap; }
    @media (pointer: coarse) { button.chip { min-height: 32px; padding: 4px 10px; } }
    /* One line: a long spot ends in an ellipsis (the details have it whole). */
    .chip .spot { color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .pop { position: absolute; z-index: 5; top: 100%; left: 0; width: max-content; max-width: min(280px, 80vw); padding: 8px 10px; border-radius: 8px;
      background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color);
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25); font-size: 12px; line-height: 1.5; pointer-events: none; }
    .pop b { display: block; font-size: 13px; margin-bottom: 2px; padding-right: 22px; }
    .si { position: absolute; top: 8px; right: 8px; --mdc-icon-size: 16px; color: var(--secondary-text-color); }
    .k { color: var(--secondary-text-color); margin-right: 4px; }

    /* The history sheet: up from the bottom on a phone, a panel on the right when wide. */
    .scrim { position: fixed; inset: 0; z-index: 10; background: rgba(0, 0, 0, 0.4); }
    .sheet { position: fixed; z-index: 11; left: 0; right: 0; bottom: 0; max-height: 80vh; display: flex; flex-direction: column;
      background: var(--card-background-color); color: var(--primary-text-color); border-radius: 16px 16px 0 0; box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.3);
      padding-bottom: env(safe-area-inset-bottom, 0px); }
    @media (min-width: 601px) { .sheet { left: auto; top: 0; width: 400px; max-height: none; border-radius: 0; box-shadow: -4px 0 20px rgba(0, 0, 0, 0.3); } }
    .sh { display: flex; align-items: flex-start; gap: 8px; padding: 14px 16px 8px; border-bottom: 1px solid var(--divider-color); }
    .sh div { flex: 1; min-width: 0; }
    .sh b { display: block; font-size: 16px; }
    .sh small { color: var(--secondary-text-color); font-size: 12px; }
    .sb { overflow-y: auto; padding: 8px 16px 16px; font-size: 13px; }
    .now { position: relative; padding: 8px 0; margin-bottom: 4px; border-bottom: 1px solid var(--divider-color); font-size: 12px; line-height: 1.6; }
    .hr { display: grid; grid-template-columns: 96px minmax(0, 1fr) auto; gap: 8px; padding: 7px 0; border-top: 1px solid var(--divider-color); align-items: baseline; }
    .hr:first-child { border-top: 0; }
    .hr .t, .hr .d, .hr .what small, .hint { color: var(--secondary-text-color); font-size: 12px; }
    .hr .t { font-variant-numeric: tabular-nums; }
    .hr .d { white-space: nowrap; }
    .hr .what { overflow-wrap: anywhere; }
    .hr.cur .d { color: var(--primary-color); }
    .hr.nowhere .what { color: var(--secondary-text-color); font-style: italic; }
  `];

  /** A chip: hovering with a mouse shows its details; a tap or click opens the person's or pet's history. */
  _chip(r, name, icon, label = name) {
    const d = chipDetail(this.hass?.states, name, r.ids, this.data?.layout?.thing_classes);
    // A person's chip shows what is tracking them (phone, watch) when that thing has a class.
    const pet = icon === "mdi:paw";   // before a person's icon becomes their device's
    if (icon === "mdi:account" && d?.thingClass) icon = classIcon(d.thingClass) || icon;
    const key = `${r.floor}|${r.room}|${name}`;
    const spot = d?.spot && d.room === r.room ? spotInRoom(d.spot, r.room, name) : null;
    return html`<span class="who"
        @pointerenter=${(e) => { if (e.pointerType === "mouse") this._hover = key; }}
        @pointerleave=${() => { if (this._hover === key) this._hover = null; }}>
      <button class="chip" aria-label=${`${label}: details and history`}
          @click=${() => { this._hover = null; this._openHistory({ kind: "person", name, label, pet, ids: r.ids }); }}>
        <ha-icon icon=${icon}></ha-icon>${label}${spot ? html`<span class="spot">&nbsp;· ${spot}</span>` : nothing}</button>
      ${this._hover === key ? html`<div class="pop" role="tooltip"><b>${name}</b>${this._details(d, pet)}</div>` : nothing}
    </span>`;
  }

  /** Where a person or pet is now, what tracks them and how sure Sextant is. */
  _details(d, pet = false) {
    if (!d) return html`No Sextant location sensor found.`;
    const row = (k, v) => (v == null || v === "" ? nothing : html`<div><span class="k">${k}</span>${v}</div>`);
    const age = d.heardAt ? fmtAge((Date.now() - d.heardAt) / 1000) + " ago" : null;   // "here" says nothing more: Here for is above
    // A pet is its own tag: "Tracked by Cat" says nothing.
    const device = pet ? null : d.thing ? (THING_CLASSES.find(([k]) => k && k === d.thingClass) || [])[1] || d.thing : d.tracker;
    let src = WHERE_SOURCE[d.source] || d.source;
    if (d.source === "wifi" && d.accessPoint) src += ` (${d.accessPoint})`;
    if (d.source === "gps" && d.gpsAccuracy != null) src += ` (±${fmtLen(d.gpsAccuracy, this.hass, 0)})`;
    // The stay-lifted figure, with the single fit's own beside it when they differ.
    const pct = (x) => `${Math.round(x * 100)}%`;
    const conf = d.conf == null ? null : d.settled == null || pct(d.settled) === pct(d.conf) ? pct(d.conf) : `${pct(d.settled)} (fit ${pct(d.conf)})`;
    return html`
      ${d.source ? html`<ha-icon class="si" icon=${WHERE_ICON[d.source] || "mdi:help-circle-outline"} title=${src}></ha-icon>` : nothing}
      ${d.outside ? row("Where", "Outside") : html`
        ${row("Room", d.room && d.room !== "unknown" ? d.room : "Unknown")}
        ${row("Spot", d.spot)}
        ${row("Floor", d.floor && d.floor !== "unknown" ? d.floor : null)}`}
      ${row(d.outside ? "Out for" : "Here for", d.since ? fmtAge((Date.now() - d.since) / 1000) : null)}
      ${row("Tracked by", device)}
      ${row("Confidence", conf)}
      ${row("Last heard", age ? `${age}${d.presence && d.presence !== "here" ? ` (${d.presence})` : ""}` : d.presence !== "here" ? d.presence : null)}`;
  }

  async _openHistory(subject) {
    this._opener = this.shadowRoot?.activeElement || null;
    this._subject = subject;
    this._hist = null;
    const token = (this._token = {});
    const all = trackedPeople(this.hass?.states);
    const people = subject.kind === "person" ? all.filter((p) => p.name === subject.name) : all;
    const now = Date.now() / 1000;
    try {
      // Home Assistant's recorder keeps every state of the room and floor sensors, and any user may read it.
      const r = people.length ? await this.hass.callWS({
        type: "history/history_during_period", start_time: new Date((now - HISTORY_HOURS * 3600) * 1000).toISOString(),
        entity_ids: people.flatMap((p) => [p.room, p.floor]), minimal_response: true, no_attributes: true, significant_changes_only: false,
      }) : {};
      if (token !== this._token) return;
      const end = Date.now() / 1000;
      this._hist = { people: people.map((p) => ({ name: p.name, pet: p.pet, stays: staysFromHistory(r?.[p.room], r?.[p.floor], end) })) };
    } catch (e) {
      if (token === this._token) this._hist = { error: e?.message || String(e) };
    }
  }

  _closeHistory() {
    this._subject = null; this._hist = null; this._token = null;
    this._opener?.focus?.();
  }

  updated(changed) {
    if (changed.get("_subject") === null && this._subject) this.shadowRoot?.querySelector(".sheet .close")?.focus();
  }

  _renderHistory() {
    const s = this._subject, h = this._hist, now = Date.now() / 1000;
    const title = s.kind === "person" ? s.label : s.kind === "room" ? s.room : s.floor;
    const rows = h?.people ? subjectHistory(h.people, s) : [];
    const floors = new Set(rows.map((r) => r.floor).filter(Boolean));
    const what = (r) => s.kind === "person"
      ? (r.room ? html`${r.room}${floors.size > 1 && r.floor ? html` <small>· ${r.floor}</small>` : nothing}` : "Not placed")
      : html`${r.pet ? r.name : firstName(r.name)}${s.kind === "floor" ? html` <small>· ${r.room}</small>` : nothing}`;
    let body;
    if (!h) body = html`<div class="hint">Loading…</div>`;
    else if (h.error) body = html`<div class="hint">History is not available (${h.error}). It comes from Home Assistant's recorder, so the people's and pets' room and floor sensors need to be recorded.</div>`;
    else if (!rows.length) body = html`<div class="hint">${s.kind === "person" ? "No history" : "Nobody"} in the last ${HISTORY_HOURS} hours.</div>`;
    else body = rows.map((r) => {
      const cur = r.end >= now - 1;
      return html`<div class="hr ${cur ? "cur" : ""} ${r.room ? "" : "nowhere"}">
        <span class="t">${clockAt(r.start, now)}</span>
        <span class="what">${what(r)}</span>
        <span class="d">${cur ? `now · ${fmtAge(now - r.start)}` : fmtAge(r.end - r.start)}</span></div>`;
    });
    const d = s.kind === "person" ? chipDetail(this.hass?.states, s.name, s.ids, this.data?.layout?.thing_classes) : null;
    return html`<div class="scrim" @click=${() => this._closeHistory()}></div>
      <div class="sheet" role="dialog" aria-modal="true" aria-label=${`${title}: history`}>
        <div class="sh"><div><b>${title}</b><small>${s.kind === "room" ? `${s.floor} · ` : ""}last ${HISTORY_HOURS} hours</small></div>
          <button class="iconbtn close" title="Close" aria-label="Close" @click=${() => this._closeHistory()}><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="sb">
          ${s.kind === "person" ? html`<div class="now">${this._details(d, s.pet)}</div>` : nothing}
          ${body}
        </div>
      </div>`;
  }

  _room(f, r) {
    const icons = r.on ? r.sources : [];
    return html`<div class="row ${r.on ? (r.peopleOn ? "on" : "pets") : ""} ${r.mode ? "mode" : ""}">
      <div class="rn">${f.outside ? "Outside" : this._roomLink(r)}${r.mode ? html`<span class="ml">${r.mode}</span>` : nothing}</div>
      <div class="w">
        ${r.people.map((p) => this._chip(r, p, "mdi:account", firstName(p)))}
        ${r.pets.map((p) => this._chip(r, p, "mdi:paw"))}
      </div>
      <span class="since" title="When the room last turned on or off">${r.since ? clockAt(r.since) : ""}</span>
      <div class="src">${icons.map((x) => html`<ha-icon icon=${SOURCE_ICON[x] || "mdi:help-circle-outline"} title=${SOURCE_LABEL[x] || x}></ha-icon>`)}${r.mode ? html`<ha-icon class="mi" icon=${modeIcon(r.mode)} title=${r.mode}></ha-icon>` : nothing}</div>
    </div>`;
  }

  _roomLink(r) {
    return html`<button class="link" aria-label=${`${r.room}: history`} @click=${() => this._openHistory({ kind: "room", room: r.room, floor: r.floor })}>${r.room}</button>`;
  }

  render() {
    const floors = this._floors || [];
    if (!floors.length && !this._outside) return html`<div class="empty">No room sensors yet. Draw rooms in Edit.</div>`;
    const people = new Set(floors.flatMap((f) => f.rooms.flatMap((r) => r.people))).size;
    return html`${[...floors, ...(this._outside ? [this._outside] : [])].map((f) => {
      const active = f.rooms.filter(isActive), quiet = f.rooms.filter((r) => !isActive(r));
      return html`<div class="floor">
        <div class="fh">${f.outside ? html`<span class="fname">${f.name}</span>`
          : html`<button class="link fname" aria-label=${`${f.name}: history`} @click=${() => this._openHistory({ kind: "floor", floor: f.name })}>${f.name}</button>`}
          <span class="pill ${f.people ? "on" : ""}">${f.people} ${f.people === 1 ? "person" : "people"}</span>
          ${f.pets ? html`<span class="pill">${f.pets} ${f.pets === 1 ? "pet" : "pets"}</span>` : nothing}</div>
        ${repeat(active, (r) => r.room, (r) => this._room(f, r))}
        ${quiet.length ? html`<div class="quiet">${active.length ? "Empty" : "Nobody"}: ${quiet.map((r, i) => html`${i ? ", " : ""}${this._roomLink(r)}`)}</div>` : nothing}
      </div>`;
    })}
      <div class="foot">${people} ${people === 1 ? "person" : "people"} in the house</div>
      ${this._subject ? this._renderHistory() : nothing}`;
  }
}
if (!customElements.get("sextant-occupancy")) customElements.define("sextant-occupancy", SextantOccupancy);
