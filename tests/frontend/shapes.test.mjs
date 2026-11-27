// What a save would destroy (sextant-shapes.js). Run: node --test tests/frontend
import { test } from "node:test";
import assert from "node:assert/strict";
import { lostShapes, planKey } from "../../custom_components/sextant/frontend/sextant-shapes.js";

const pts = (n) => Array.from({ length: n }, (_, i) => ({ x: i, y: i * 2 }));
const layout = (spots, rooms = []) => ({
  floor: [{
    name: "Second Floor",
    zones: rooms.map(([name, n], i) => ({ zone_id: `z${i}`, entity_id: name, cords: pts(n) })),
    subzones: spots.map(([name, n], i) => ({ sub_zone_id: `s${i}`, entity_id: name, cords: pts(n) })),
  }],
});

test("an untouched plan loses nothing", () => {
  const a = layout([["Alex Bedside Table", 4]]);
  assert.deepEqual(lostShapes(a, JSON.parse(JSON.stringify(a))), []);
});

test("a spot collapsing to one point is reported - the bedside-table bug", () => {
  const before = layout([["Alex Bedside Table", 4], ["Sam Bedside Table", 4]]);
  const after = layout([["Alex Bedside Table", 1], ["Sam Bedside Table", 1]]);
  const lost = lostShapes(before, after);
  assert.equal(lost.length, 2);
  assert.match(lost[0], /Alex Bedside Table.*4 corners to 1/);
});

test("a room collapsing is reported too", () => {
  assert.equal(lostShapes(layout([], [["Master Bedroom", 8]]), layout([], [["Master Bedroom", 2]])).length, 1);
});

test("reshaping, deleting and adding are not losses", () => {
  assert.deepEqual(lostShapes(layout([["Couch", 8]]), layout([["Couch", 4]])), []);
  assert.deepEqual(lostShapes(layout([["Couch", 8], ["Pantry", 4]]), layout([["Couch", 8]])), []);
  assert.deepEqual(lostShapes(layout([["Couch", 8]]), layout([["Couch", 8], ["New", 4]])), []);
});

test("junk in does not throw", () => {
  assert.deepEqual(lostShapes(null, undefined), []);
  assert.deepEqual(lostShapes({ floor: [null] }, { floor: [{ name: "F", zones: [null] }] }), []);
});

test("planKey ignores what the server writes and sees what the editor would overwrite", () => {
  const a = layout([["Alex Bedside Table", 4]], [["Master Bedroom", 8]]);
  a.floor[0].receivers = [{ entity_id: "p1", cords: { x: 1, y: 2 } }];
  const b = JSON.parse(JSON.stringify(a));
  b.tuning = { history_hours: 3 };
  b.floor[0].calibration = { at: 1 };
  b.floor[0].bias_field = { cells: [] };
  b.floor[0].receivers[0].correction = 0.92;
  b.floor[0].receivers[0].unmatched = true;
  assert.equal(planKey(a), planKey(b));
  b.floor[0].receivers[0].cords.x = 5;   // a proxy moved from the Health page
  assert.notEqual(planKey(a), planKey(b));
  // A proxy held out of calibration: its correction is the editor's to overwrite.
  const c = JSON.parse(JSON.stringify(a)), e = JSON.parse(JSON.stringify(a));
  Object.assign(c.floor[0].receivers[0], { calibrate: false, correction: 0.8 });
  Object.assign(e.floor[0].receivers[0], { calibrate: false, correction: 1.2 });
  assert.notEqual(planKey(c), planKey(e));
  assert.equal(planKey(undefined), "[]");
});
