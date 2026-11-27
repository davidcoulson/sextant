// The room setup wizard's suggestions (sextant-room-setup.js). Run: node --test tests/frontend
import { test } from "node:test";
import assert from "node:assert/strict";
import { ROOM_STEPS, areaEntities, suggestions, picked, toggled } from "../../custom_components/sextant/frontend/sextant-room-setup.js";

const st = (entity_id, device_class, friendly_name) => ({ entity_id, attributes: { device_class, friendly_name } });
const hass = {
  devices: { d1: { area_id: "den" } },
  entities: {
    "binary_sensor.den_motion": { entity_id: "binary_sensor.den_motion", device_id: "d1" },
    "media_player.den_tv": { entity_id: "media_player.den_tv", area_id: "den" },
    "sensor.den_lux": { entity_id: "sensor.den_lux", area_id: "den" },
    "binary_sensor.den_door": { entity_id: "binary_sensor.den_door", area_id: "den" },
    "binary_sensor.den_sextant_occupancy": { entity_id: "binary_sensor.den_sextant_occupancy", area_id: "den" },
    "binary_sensor.hall_motion": { entity_id: "binary_sensor.hall_motion", area_id: "hall" },
    "input_select.den_mode": { entity_id: "input_select.den_mode", area_id: "den", hidden: true },
  },
  states: {
    "binary_sensor.den_motion": st("binary_sensor.den_motion", "motion", "Den motion"),
    "media_player.den_tv": st("media_player.den_tv", undefined, "Den TV"),
    "sensor.den_lux": st("sensor.den_lux", "illuminance"),
    "binary_sensor.den_door": st("binary_sensor.den_door", "door"),
    "binary_sensor.den_sextant_occupancy": st("binary_sensor.den_sextant_occupancy", "occupancy"),
    "binary_sensor.hall_motion": st("binary_sensor.hall_motion", "motion"),
    "input_select.den_mode": st("input_select.den_mode"),
  },
};

test("the area's own entities, by entity or device, without Sextant's or hidden ones", () => {
  const ids = areaEntities(hass, "den").map((s) => s.entity_id).sort();
  assert.deepEqual(ids, ["binary_sensor.den_door", "binary_sensor.den_motion", "media_player.den_tv", "sensor.den_lux"]);
  assert.deepEqual(areaEntities(hass, undefined), []);
});

test("each step suggests its own kind of sensor", () => {
  const states = areaEntities(hass, "den");
  assert.deepEqual(suggestions("inputs", states), [{ value: "binary_sensor.den_motion", label: "Den motion" }]);
  assert.deepEqual(suggestions("keep", states).map((s) => s.value), ["media_player.den_tv"]);
  assert.deepEqual(suggestions("door", states).map((s) => s.value), ["binary_sensor.den_door"]);
  assert.deepEqual(suggestions("dark", states).map((s) => s.value), ["sensor.den_lux<20"]);
  assert.deepEqual(suggestions("timing", states), []);
});

test("clicking a suggestion adds it, and again takes it out", () => {
  assert.equal(toggled(undefined, "binary_sensor.a", true), "binary_sensor.a");
  assert.equal(toggled("binary_sensor.a", "media_player.b", true), "binary_sensor.a, media_player.b");
  assert.equal(toggled(["binary_sensor.a", "media_player.b"], "binary_sensor.a", true), "media_player.b");
  assert.equal(toggled("binary_sensor.a", "binary_sensor.a", true), undefined);
  assert.equal(toggled("sensor.desk_power > 50", "media_player.b", true), "sensor.desk_power>50, media_player.b");   // a spaced test stays whole
  assert.equal(toggled("sensor.lux<5", "sensor.lux<20", false), undefined);   // the same sensor, whatever its threshold
  assert.equal(toggled("binary_sensor.old", "binary_sensor.new", false), "binary_sensor.new");
  assert.ok(picked("sensor.lux<5", "sensor.lux<20") && !picked("", "sensor.lux<20"));
});

test("every field belongs to one step", () => {
  const keys = ROOM_STEPS.flatMap((s) => s.fields.map((f) => f.key));
  assert.equal(new Set(keys).size, keys.length);
  for (const s of ROOM_STEPS) if (s.pick) assert.ok(s.fields.some((f) => f.key === s.pick), s.key);
});
