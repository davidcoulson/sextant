// Shared by the dashboard cards' visual editors. No Lit, so the option helper loads in node tests.

// HA's form, card picker and card editor are lazy; opening its own conditional card's editor loads them.
let _ready = null;
export function loadHaEditors() {
  const tags = ["ha-form", "hui-card-picker", "hui-card-element-editor"];
  let done = false;
  return _ready ||= Promise.race([
    (async () => {
      if (!tags.every((t) => customElements.get(t))) {
        const helpers = await window.loadCardHelpers();
        // Built-in cards load lazily too: the element may not be upgraded yet, so wait for its class.
        helpers.createCardElement({ type: "conditional", conditions: [], card: { type: "markdown", content: "" } });
        await (await customElements.whenDefined("hui-conditional-card"))?.getConfigElement?.();
      }
      await Promise.all(tags.map((t) => customElements.whenDefined(t)));
      done = true;
    })().catch(() => {}),
    // Gives up after 5 s: the editor draws what is defined, and the next one opened tries again.
    new Promise((r) => setTimeout(() => { if (!done) _ready = null; r(); }, 5000)),
  ]);
}

const insideHa = (el) => { for (let n = el; n; n = n.parentNode || n.host) if (n.localName === "home-assistant") return true; return false; };
let _probe = null;
/**
 * HA's selectors ask the page for translations, registries and the like (Lit context requests, answered by
 * <home-assistant>). A card editor in a dialog outside it (a swipe card's) gets no answer and its pickers draw
 * nothing, so its requests are sent again from inside HA's root.
 */
export function forwardHaContext(host) {
  host.addEventListener("context-request", (ev) => {
    if (ev.sextantForwarded || insideHa(host)) return;
    const root = document.querySelector("home-assistant")?.shadowRoot;
    if (!root) return;
    if (!_probe?.isConnected) { _probe = document.createElement("span"); _probe.hidden = true; root.appendChild(_probe); }
    ev.stopPropagation();
    // The provider ignores a request that comes from its own host, so it is sent from a child of HA's root.
    const copy = new Event("context-request", { bubbles: true, composed: true });
    Object.assign(copy, { context: ev.context, callback: ev.callback, subscribe: ev.subscribe, contextTarget: ev.contextTarget ?? ev.composedPath()[0], sextantForwarded: true });
    _probe.dispatchEvent(copy);
  });
}

/** Select options for the entities whose id passes `test`, labelled by `label(id, state)` and sorted; ids in `keep` stay even when missing. */
export function entityOptions(states, test, label, keep = []) {
  const ids = new Set([...Object.keys(states || {}).filter(test), ...keep.filter(Boolean)]);
  return [...ids].map((id) => ({ value: id, label: states?.[id] ? label(id, states[id]) : id })).sort((x, y) => x.label.localeCompare(y.label));
}
