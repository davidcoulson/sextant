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

/** Select options for the entities whose id passes `test`, labelled by `label(id, state)` and sorted; ids in `keep` stay even when missing. */
export function entityOptions(states, test, label, keep = []) {
  const ids = new Set([...Object.keys(states || {}).filter(test), ...keep.filter(Boolean)]);
  return [...ids].map((id) => ({ value: id, label: states?.[id] ? label(id, states[id]) : id })).sort((x, y) => x.label.localeCompare(y.label));
}
