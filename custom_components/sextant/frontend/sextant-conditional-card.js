/**
 * Sextant conditional card for Lovelace: shows another card only while the person viewing the
 * dashboard (or a named person) is in one of some rooms or on one of some floors, and/or only
 * for some dashboard users.
 *
 *   type: custom:sextant-conditional-card
 *   rooms: [Kitchen, Butler Pantry]   # in any of these rooms...
 *   floors: [Basement]                # ...or anywhere on these floors
 *   users: [<user id>]                # only for these dashboard users (optional)
 *   person: person.alex_smith         # whose place (optional; default: whoever is viewing)
 *   card:
 *     type: markdown
 *     content: Recipes
 *
 * The viewer's person is the person.* whose user_id is the viewing user; their place is
 * sensor.<person>_sextant_person_location's room and floor. Away matches no room or floor.
 *
 * Resource: /sextant/sextant-conditional-card.js (module).
 *
 * Behind Strimmer the person and location entities are not in the card's config, so the card
 * asks for them.
 */
import { LitElement, html, css, nothing } from "./lit.js";
import { askStrimmer } from "./sextant-occupancy-data.js";
import { personForUser, placeOf, shows, testsPlace, choices } from "./sextant-conditional.js";
import { forwardHaContext, loadHaEditors } from "./sextant-ha-editors.js";

class SextantConditionalCard extends LitElement {
  static properties = { hass: { attribute: false }, preview: { type: Boolean }, editMode: { type: Boolean }, _card: { state: true } };

  static getConfigElement() { return document.createElement("sextant-conditional-card-editor"); }

  static getStubConfig(hass) {
    const room = Object.values(hass?.states || {}).find((s) => s.entity_id?.endsWith("_sextant_occupancy"))?.attributes?.room;
    return { rooms: room ? [room] : [], card: { type: "markdown", content: room ? `You're in the ${room}.` : "You're here." } };
  }

  setConfig(config) {
    if (!config?.card?.type) throw new Error("card: the card to show");
    this._config = config;
    this._build();
  }

  async _build() {
    const config = this._config;
    let el;
    if (customElements.get("hui-card")) {
      // HA's own card wrapper, as its stack cards use: it loads the card, keeps its grid size and applies the
      // inner card's own visibility conditions. Built at once, so the section reads the right size.
      el = document.createElement("hui-card");
      if (this.hass) el.hass = this.hass;
      el.preview = this.preview;
      el.config = config.card;
      el.load?.();
      // The inner card's own visibility hides only the wrapper; fold it into ours so a section leaves no gap.
      el.addEventListener("card-visibility-changed", (e) => { e.stopPropagation(); this.requestUpdate(); });
    } else {
      const helpers = await window.loadCardHelpers();
      if (config !== this._config) return;
      el = helpers.createCardElement(config.card);
      el.addEventListener("ll-rebuild", (e) => { e.stopPropagation(); this._build(); });
    }
    if (this.hass) el.hass = this.hass;
    el.preview = this.preview;
    this._card = el;
  }

  getCardSize() { return this._on && this._card?.getCardSize ? this._card.getCardSize() : 0; }
  getGridOptions() { return this._card?.getGridOptions?.() ?? {}; }
  getLayoutOptions() { return this._card?.getLayoutOptions?.() ?? {}; }

  _visible() {
    // Shown while editing, so the card can be found and changed.
    if (this.preview || this.editMode) return true;
    if (this._card?.localName === "hui-card" && this._card.hidden) return false;
    const states = this.hass?.states, userId = this.hass?.user?.id;
    let place = { room: null, floor: null };
    if (testsPlace(this._config)) {
      let person = this._config.person;
      if (!person) {
        // Cached: finding it scans every entity. Looked up again when the person is no longer linked to this user.
        if (!userId || states?.[this._person]?.attributes?.user_id !== userId) this._person = personForUser(states, userId);
        person = this._person;
      }
      place = placeOf(states, person);
    }
    return shows(this._config, { userId, ...place });
  }

  willUpdate() {
    if (!this._config || !this.hass) return;
    const on = this._visible();
    if (on === this._on) return;
    this._on = on;
    this.toggleAttribute("hidden", !on);
    // Home Assistant's card wrapper (sections) hides its slot on this, as for its own conditional card.
    this.dispatchEvent(new CustomEvent("card-visibility-changed", { detail: { value: on }, bubbles: true, composed: true }));
  }

  updated(changed) {
    if (changed.has("hass")) {
      // Strimmer forwards only what dashboards name; the viewer's person and location sensor are found at runtime.
      askStrimmer(this.hass?.connection);
      if (this._card) this._card.hass = this.hass;
    }
    if (changed.has("preview") && this._card) this._card.preview = this.preview;
  }

  // Kept in the page while hidden (the host is display: none), so the inner hui-card keeps checking its own visibility.
  render() { return this._card ? html`${this._card}` : nothing; }

  static styles = css`:host([hidden]) { display: none; }`;
}

const LABELS = {
  rooms: "In any of these rooms",
  floors: "Or anywhere on these floors",
  users: "Only for these dashboard users",
  person: "Whose place (blank: whoever is viewing)",
};

class SextantConditionalCardEditor extends LitElement {
  static properties = { hass: { attribute: false }, lovelace: { attribute: false }, _config: { state: true }, _ready: { state: true }, _picking: { state: true } };

  constructor() { super(); forwardHaContext(this); }

  setConfig(config) { this._config = config; }

  connectedCallback() { super.connectedCallback(); loadHaEditors().then(() => { this._ready = true; }); }

  _fire(config) {
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  _conditions(e) {
    e.stopPropagation();
    const config = { ...this._config };
    for (const [k, v] of Object.entries(e.detail.value)) {
      if (v == null || v === "" || (Array.isArray(v) && !v.length)) delete config[k]; else config[k] = v;
    }
    this._fire(config);
  }

  _card(e) {
    e.stopPropagation();
    if (!e.detail?.config) return;
    this._picking = false;
    this._fire({ ...this._config, card: e.detail.config });
  }

  render() {
    if (!this.hass || !this._config) return nothing;
    if (!this._ready) return html`<div class="wait">Loading…</div>`;
    const ch = choices(this.hass.states);
    const schema = [
      { name: "rooms", selector: { select: { multiple: true, mode: "dropdown", options: ch.rooms } } },
      { name: "floors", selector: { select: { multiple: true, options: ch.floors } } },
      { name: "users", selector: { select: { multiple: true, options: ch.users } } },
      { name: "person", selector: { entity: { filter: { domain: "person" } } } },
    ];
    const c = this._config;
    const data = { rooms: c.rooms || [], floors: c.floors || [], users: c.users || [], person: c.person || "" };
    const card = c.card && !this._picking;
    return html`
      <h3>Show when</h3>
      <p class="hint">The card shows when the person is in one of the rooms or on one of the floors, and the viewer is one of the users. Leave a list empty to skip it. Away matches no room.</p>
      <ha-form .hass=${this.hass} .data=${data} .schema=${schema} .computeLabel=${(s) => LABELS[s.name] || s.name} @value-changed=${this._conditions}></ha-form>
      <div class="head"><h3>Card</h3>${card ? html`<ha-button @click=${() => { this._picking = true; }}>Change card type</ha-button>`
        : c.card ? html`<ha-button @click=${() => { this._picking = false; }}>Cancel</ha-button>` : nothing}</div>
      ${card
        ? html`<hui-card-element-editor .hass=${this.hass} .lovelace=${this.lovelace} .value=${c.card} @config-changed=${this._card} @GUImode-changed=${(e) => e.stopPropagation()}></hui-card-element-editor>`
        : html`<hui-card-picker .hass=${this.hass} .lovelace=${this.lovelace} @config-changed=${this._card}></hui-card-picker>`}`;
  }

  static styles = css`
    h3 { margin: 16px 0 4px; font-size: 16px; font-weight: 500; }
    h3:first-child { margin-top: 0; }
    .hint { margin: 0 0 8px; color: var(--secondary-text-color); font-size: 13px; }
    .head { display: flex; align-items: center; justify-content: space-between; margin-top: 16px; }
    .head h3 { margin: 0; }
    .wait { padding: 16px; color: var(--secondary-text-color); }
  `;
}

if (!customElements.get("sextant-conditional-card")) customElements.define("sextant-conditional-card", SextantConditionalCard);
if (!customElements.get("sextant-conditional-card-editor")) customElements.define("sextant-conditional-card-editor", SextantConditionalCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({ type: "sextant-conditional-card", name: "Sextant Conditional", description: "Shows another card only while you (or someone) are in some rooms or floors, or for some users.", preview: false, documentationURL: "https://github.com/davidcoulson/sextant" });
