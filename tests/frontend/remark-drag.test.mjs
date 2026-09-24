// Dragging a note in the editor moves the note, and nothing else.
import { test } from "node:test";
import assert from "node:assert/strict";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.window = globalThis.window || { devicePixelRatio: 1 };
const { SextantMap } = await import("../../custom_components/sextant/frontend/sextant-map.js");

function fakeCanvas() {
  const ctx = new Proxy({}, { get: () => () => ({ addColorStop() {} }), set: () => true });
  const listeners = new Map();
  return {
    style: {}, width: 400, height: 800, listeners,
    getContext: () => ctx,
    addEventListener(type, fn) { listeners.set(type, fn); },
    removeEventListener(type, fn) { if (listeners.get(type) === fn) listeners.delete(type); },
    setPointerCapture() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 800 }),
  };
}

const ev = (type, id, x, y) => ({ type, pointerId: id, clientX: x, clientY: y, button: 0, pointerType: "mouse", altKey: false });

test("a dragged note moves, lands rounded, and leaves the spots alone", () => {
  const changes = [];
  const map = new SextantMap(fakeCanvas(), { onChange: (kind, index) => changes.push([kind, index]) });
  const spot = [{ x: 10, y: 10 }, { x: 20, y: 10 }, { x: 20, y: 20 }];
  map.floor = { name: "F", scale: 100, receivers: [], zones: [], subzones: [{ name: "s", cords: spot.map((q) => ({ ...q })) }], remarks: [{ remark_id: "r1", text: "hi", cords: { x: 200, y: 200 } }] };
  map.view = { k: 1, tx: 0, ty: 0 };
  map.invalidate = () => {};
  map.setMode("edit");
  map._drag = { kind: "item", hit: { kind: "remark", index: 0 }, start: { x: 200, y: 200 }, moved: false, origin: map._itemPoints({ kind: "remark", index: 0 }) };
  map._move(ev("pointermove", 1, 230.12345, 190));
  assert.deepEqual(map.floor.remarks[0].cords, { x: 230.12345, y: 190 });
  map._up(ev("pointerup", 1, 230.12345, 190));
  assert.deepEqual(map.floor.remarks[0].cords, { x: 230.123, y: 190 });
  assert.deepEqual(map.floor.subzones[0].cords, spot);
  assert.deepEqual(changes, [["remark", 0]]);
});

test("destroy takes the canvas listeners off again", () => {
  const canvas = fakeCanvas();
  const map = new SextantMap(canvas, {});
  assert.ok(canvas.listeners.size > 0);
  map.destroy();
  assert.equal(canvas.listeners.size, 0);
  assert.equal(map._raf, 0);
});
