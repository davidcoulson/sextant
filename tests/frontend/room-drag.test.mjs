// Dragging a room whole: it takes its spots (and with Shift everything inside),
// snaps home near its start, and Esc puts it all back. Run: node --test tests/frontend
import { test } from "node:test";
import assert from "node:assert/strict";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.window = globalThis.window || { devicePixelRatio: 1 };
const { SextantMap } = await import("../../custom_components/sextant/frontend/sextant-map.js");

function fakeCanvas() {
  const ctx = new Proxy({}, { get: () => () => ({ addColorStop() {} }), set: () => true });
  return { style: {}, width: 800, height: 800, getContext: () => ctx, addEventListener() {}, removeEventListener() {}, setPointerCapture() {},
           getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 800 }) };
}
const ev = (type, x, y, shift = false) => ({ type, pointerId: 1, clientX: x, clientY: y, button: 0, pointerType: "mouse", altKey: false, shiftKey: shift });
const rect = (x0, y0, x1, y1) => [{ x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 }];

function editMap() {
  const changes = [];
  const map = new SextantMap(fakeCanvas(), { onChange: (kind, index) => changes.push([kind, index]) });
  map.floor = {
    name: "Ground", scale: 100,
    zones: [{ zone_id: "z1", entity_id: "Kitchen", cords: rect(100, 100, 400, 400), poly: true },
            { zone_id: "z2", entity_id: "Dining", cords: rect(500, 100, 700, 400), poly: true }],
    subzones: [{ entity_id: "Island", parent: "z1", cords: rect(200, 200, 260, 240) },
               { entity_id: "Table", parent: "z2", cords: rect(550, 200, 600, 240) }],
    receivers: [{ entity_id: "kitchen_proxy", cords: { x: 150, y: 150 } }, { entity_id: "dining_proxy", cords: { x: 600, y: 150 } }],
    pins: [{ name: "Anchor 1", cords: { x: 100, y: 100 } }], remarks: [], radars: [], access_points: [{ mac: "aa:bb:cc:dd:ee:ff", cords: { x: 300, y: 300 } }],
  };
  map.view = { k: 1, tx: 0, ty: 0 };
  map.invalidate = () => {};
  map.setMode("edit");
  map.setLocks({ zone: false });
  return { map, changes };
}
const start = (map, x, y, shift) => {
  const hit = map.hitTest({ x, y });
  assert.equal(hit?.kind, "zone");
  map._down(ev("pointerdown", x, y, shift));
};

test("a room dragged whole takes its own spot, and leaves the proxies, the anchor and the other room", () => {
  const { map, changes } = editMap();
  start(map, 350, 350);
  map._move(ev("pointermove", 400, 380));
  map._up(ev("pointerup", 400, 380));
  const f = map.floor;
  assert.deepEqual(f.zones[0].cords[0], { x: 150, y: 130 });
  assert.deepEqual(f.subzones[0].cords[0], { x: 250, y: 230 });                // the Island went with the Kitchen
  assert.deepEqual(f.subzones[1].cords[0], { x: 550, y: 200 });                // the Dining Room's Table did not
  assert.deepEqual(f.receivers[0].cords, { x: 150, y: 150 });                  // proxies stay without Shift
  assert.deepEqual(f.pins[0].cords, { x: 100, y: 100 });
  assert.deepEqual(changes, [["zone", 0]]);
});

test("with Shift it takes everything inside: proxies and access points too, never the anchors", () => {
  const { map } = editMap();
  start(map, 350, 350, true);
  map._move(ev("pointermove", 400, 380, true));
  map._up(ev("pointerup", 400, 380, true));
  const f = map.floor;
  assert.deepEqual(f.receivers[0].cords, { x: 200, y: 180 });
  assert.deepEqual(f.receivers[1].cords, { x: 600, y: 150 });                  // the other room's proxy stays
  assert.deepEqual(f.access_points[0].cords, { x: 350, y: 330 });
  assert.deepEqual(f.pins[0].cords, { x: 100, y: 100 });
});

test("brought back near where it started, the room snaps exactly home", () => {
  const { map } = editMap();
  start(map, 350, 350);
  map._move(ev("pointermove", 420, 400));
  map._move(ev("pointermove", 355, 354));
  map._up(ev("pointerup", 355, 354));
  assert.deepEqual(map.floor.zones[0].cords, rect(100, 100, 400, 400));
  assert.deepEqual(map.floor.subzones[0].cords, rect(200, 200, 260, 240));
});

test("Esc in the middle of a drag puts the room and what it carried back", () => {
  const { map, changes } = editMap();
  start(map, 350, 350, true);
  map._move(ev("pointermove", 450, 450, true));
  assert.ok(map.cancelDrag());
  assert.deepEqual(map.floor.zones[0].cords, rect(100, 100, 400, 400));
  assert.deepEqual(map.floor.subzones[0].cords, rect(200, 200, 260, 240));
  assert.deepEqual(map.floor.receivers[0].cords, { x: 150, y: 150 });
  map._up(ev("pointerup", 450, 450, true));                                     // the release after Esc changes nothing
  assert.deepEqual(changes, []);
  assert.equal(map.cancelDrag(), false);
});

test("a corner of a shape being drawn can be taken back", () => {
  const { map } = editMap();
  map.draft = [{ x: 1, y: 1 }, { x: 2, y: 2 }];
  assert.ok(map.undoDraftPoint());
  assert.deepEqual(map.draft, [{ x: 1, y: 1 }]);
  assert.ok(map.undoDraftPoint());
  assert.equal(map.draft, null);
  assert.equal(map.undoDraftPoint(), false);
});

test("a spot assigned to another room stays, even lying inside the dragged one", () => {
  const { map } = editMap();
  map.floor.subzones.push({ entity_id: "Stray", parent: "z2", cords: rect(300, 300, 320, 320) });
  start(map, 350, 350);
  map._move(ev("pointermove", 400, 380));
  map._up(ev("pointerup", 400, 380));
  assert.deepEqual(map.floor.subzones[2].cords[0], { x: 300, y: 300 });
});

test("a room dropped back home reports no change", () => {
  const { map, changes } = editMap();
  start(map, 350, 350);
  map._move(ev("pointermove", 420, 400));
  map._move(ev("pointermove", 352, 351));
  map._up(ev("pointerup", 352, 351));
  assert.deepEqual(map.floor.zones[0].cords[0], { x: 100, y: 100 });
  assert.deepEqual(changes, []);
});

test("the pointer-up after Esc is not a click", () => {
  const { map } = editMap();
  start(map, 350, 350);
  map._move(ev("pointermove", 420, 400));
  assert.equal(map.cancelDrag(), true);
  map._up(ev("pointerup", 420, 400));
  assert.equal(map.lastDragMoved, true);
  map._down(ev("pointerdown", 600, 600));
  map._up(ev("pointerup", 600, 600));
  assert.equal(map.lastDragMoved, false);
});

test("a drag the browser cancels goes back where it started", () => {
  const { map, changes } = editMap();
  start(map, 350, 350);
  map._move(ev("pointermove", 420, 400));
  // What the pointercancel listener does.
  map.cancelDrag(); map._up(ev("pointercancel", 420, 400));
  assert.deepEqual(map.floor.zones[0].cords[0], { x: 100, y: 100 });
  assert.deepEqual(map.floor.subzones[0].cords[0], { x: 200, y: 200 });
  assert.deepEqual(changes, []);
  assert.equal(map.lastDragMoved, true);
});
