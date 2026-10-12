// Lining an mmWave sensor up from one target, and how far it covers.
// Run: node --test tests/frontend
import { test } from "node:test";
import assert from "node:assert/strict";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.window = globalThis.window || { devicePixelRatio: 1 };
const { radarCalibration, radarFloorReach } = await import("../../custom_components/sextant/frontend/sextant-map.js");

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("the turn from where it put you to where you were is the facing to fix", () => {
  // Sensor at the origin, facing right (90°); it put you 3 m right, you were 3 m down: 90° clockwise off.
  const r = radarCalibration({ from: [0, 0], frozen: [300, 0], at: [0, 300], heading: 90, scale: 100 });
  assert.equal(r.turn, 90);
  assert.equal(r.heading, 180);
  near(r.reportedM, 3); near(r.actualM, 3);
  const back = radarCalibration({ from: [0, 0], frozen: [0, 300], at: [300, 0], heading: 10, scale: 100 });
  assert.equal(back.turn, -90);
  assert.equal(back.heading, 280, "wraps below 0");
});

test("a turn across the back is the short way round", () => {
  const r = radarCalibration({ from: [0, 0], frozen: [-300, 1], at: [-300, -1], heading: 0, scale: 100 });
  assert.ok(Math.abs(r.turn) <= 1, `turn ${r.turn}`);
});

test("too close to the sensor to judge", () => {
  assert.ok(radarCalibration({ from: [0, 0], frozen: [20, 0], at: [0, 300], scale: 100 }).tooClose);
  assert.ok(radarCalibration({ from: [0, 0], frozen: [300, 0], at: [10, 10], scale: 100 }).tooClose);
});

test("on the wall a distance that reads long suggests the mount height", () => {
  // It reports a 3.16 m slant (x 1, y 3); you were 3 m out: 1 m of height above a chest, so 2 m up.
  const r = radarCalibration({ from: [0, 0], frozen: [0, -316], at: [0, -300], scale: 100, x_m: 1, y_m: 3 });
  assert.equal(r.height, 2);
  const right = radarCalibration({ from: [0, 0], frozen: [0, -301], at: [0, -300], scale: 100, x_m: 0, y_m: 3.01 });
  assert.equal(right.height, null, "within 5 %: nothing to suggest");
  for (const other of [{ mount: "ceiling" }, { has_z: true }]) {
    assert.equal(radarCalibration({ from: [0, 0], frozen: [0, -316], at: [0, -300], scale: 100, x_m: 1, y_m: 3, ...other }).height, null,
      "a ceiling or 3D sensor's distance does not depend on its height");
  }
});

test("a ceiling sensor covers a circle; a wall sensor its range less the slant", () => {
  near(radarFloorReach({ mount: "ceiling", height_m: 3 }, 6, 120), 2 * Math.tan(Math.PI / 3));
  near(radarFloorReach({ mount: "ceiling", height_m: 3 }, 2.5, 120), 1.5);
  near(radarFloorReach({ height_m: 2 }, 6), Math.sqrt(35));
  near(radarFloorReach({}, 6), 6);
});
