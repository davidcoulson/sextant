// The Advice page's predicted-error map: colour bins and the value at a plan point.
import { test } from "node:test";
import assert from "node:assert/strict";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.window = globalThis.window || { devicePixelRatio: 1 };
const { errorRgb, errorAt } = await import("../../custom_components/sextant/frontend/sextant-map.js");

test("error colours run from green under a metre to red at four and over", () => {
  const [r0, g0] = errorRgb(0.5);
  assert.ok(g0 > r0);
  const [r4, g4] = errorRgb(4);
  assert.ok(r4 > g4);
  assert.deepEqual(errorRgb(8), errorRgb(4));
  assert.deepEqual(errorRgb(0), errorRgb(0.5));
});

test("errorAt reads a cell centre, blends between neighbours, and is null off the grid", () => {
  const e = { grid: { x0: 25, y0: 25, step: 50, w: 3, h: 2 }, err: [1, 3, 5, 2, 4, 6], err_after: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5] };
  assert.equal(errorAt(e, false, 75, 25), 3);
  assert.equal(errorAt(e, false, 50, 25), 2);
  assert.equal(errorAt(e, false, 125, 75), 6);
  assert.equal(errorAt(e, true, 75, 25), 0.5);
  assert.equal(errorAt(e, false, 10, 25), null);
  assert.equal(errorAt(e, false, 25, 80), null);
});
