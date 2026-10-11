// See-through fills from any colour the editor stores, and the HA colour list.
import { test } from "node:test";
import assert from "node:assert/strict";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.window = globalThis.window || { devicePixelRatio: 1 };
const { withAlpha, distanceColour } = await import("../../custom_components/sextant/frontend/sextant-map.js");

test("withAlpha makes hex, rgb and hsl see-through", () => {
  assert.equal(withAlpha("#2a9d8f", 0.22), "rgba(42, 157, 143, 0.22)");
  assert.equal(withAlpha("#fff", 0.5), "rgba(255, 255, 255, 0.5)");
  assert.equal(withAlpha("hsl(175,70%,45%)", 0.22), "hsla(175, 70%, 45%, 0.22)");
  assert.equal(withAlpha("rgb(1, 2, 3)", 0.1), "rgba(1, 2, 3, 0.1)");
  assert.equal(withAlpha("rgba(1, 2, 3, 0.9)", 0.1), "rgba(1, 2, 3, 0.1)");
  // CSS Color 4 space-separated syntax, with or without an alpha.
  assert.equal(withAlpha("rgb(1 2 3 / 50%)", 0.22), "rgb(1 2 3 / 0.22)");
  assert.equal(withAlpha("hsl(175 70% 45%)", 0.22), "hsl(175 70% 45% / 0.22)");
});

test("signal-line colours go from red far away to green close", () => {
  assert.equal(distanceColour(20), distanceColour(10));     // 10 m and further: the same red
  assert.equal(distanceColour(0.5), distanceColour(1));     // inside a metre: the same green
  assert.notEqual(distanceColour(1), distanceColour(10));
});
