// A card editor outside <home-assistant> (a swipe card's dialog) has its context requests sent again from inside HA's root.
import { test } from "node:test";
import assert from "node:assert/strict";
import { forwardHaContext } from "../../custom_components/sextant/frontend/sextant-ha-editors.js";

const node = (localName, parentNode = null) => Object.assign(new EventTarget(), { localName, parentNode });

test("a request from an editor outside HA is stopped and asked again from HA's root", () => {
  const seen = [];
  const probe = Object.assign(node("span"), { isConnected: true });
  probe.addEventListener("context-request", (e) => seen.push(e));
  const root = { appendChild: () => {} };
  globalThis.document = { querySelector: () => ({ shadowRoot: root }), createElement: () => probe };
  const host = node("sextant-where-card-editor", node("ha-dialog"));
  forwardHaContext(host);
  let stopped = false;
  const ev = new Event("context-request", { bubbles: true, composed: true });
  const callback = () => {};
  Object.assign(ev, { context: "hassInternationalization", callback, subscribe: true, contextTarget: "picker" });
  ev.stopPropagation = () => { stopped = true; };
  host.dispatchEvent(ev);
  assert.ok(stopped);
  assert.equal(seen.length, 1);
  assert.deepEqual([seen[0].context, seen[0].callback, seen[0].subscribe, seen[0].contextTarget], ["hassInternationalization", callback, true, "picker"]);
});

test("an editor inside HA is left alone", () => {
  let asked = false;
  globalThis.document = { querySelector: () => { asked = true; return null; } };
  const ha = node("home-assistant");
  const host = node("sextant-where-card-editor", { parentNode: null, host: ha });
  forwardHaContext(host);
  host.dispatchEvent(new Event("context-request"));
  assert.equal(asked, false);
});
