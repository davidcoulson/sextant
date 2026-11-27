// New rooms and spots get a name no other shape has (sextant-shapes.js). Run: node --test tests/frontend/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { freeName, sameName } from "../../custom_components/sextant/frontend/sextant-shapes.js";

test("a new shape takes the first free number, not the count plus one", () => {
  assert.equal(freeName("Room", []), "Room 1");
  assert.equal(freeName("Room", [{ entity_id: "Room 2" }]), "Room 1");            // Room 1 was deleted
  assert.equal(freeName("Room", [{ entity_id: "Room 1" }, { entity_id: "room 2 " }]), "Room 3");
});

test("two rooms of one name are flagged; a room and a no-go area are not", () => {
  const a = { entity_id: "Office" }, b = { entity_id: " office" }, c = { entity_id: "Office", no_go: true };
  assert.ok(sameName([a, b], a));
  assert.ok(!sameName([a, c], a));
  assert.ok(!sameName([a, { entity_id: "" }], { entity_id: "" }));
});
