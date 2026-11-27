// A room's occupancy settings, as the steps the room setup wizard walks through
// and the fields the plain form lists; and the sensors the wizard suggests from the
// room's Home Assistant area. Pure: no DOM, so node can test it.

const SECS = (key, label, lo, hi, tuning) => ({ key, label, num: [lo, hi], tuning });

/** Each step: what it is for, its fields (zone keys), and which field the suggestions fill (`pick`, `many` for a list). */
export const ROOM_STEPS = [
  { key: "inputs", title: "Who is here", pick: "inputs", many: true,
    help: "Tracked phones, watches and tags count on their own. Add the room's other sensors that mean someone is here - motion, presence, or a number past a threshold - so a guest with no beacon counts too.",
    fields: [{ key: "inputs", label: "Sensors that mean someone is here (entity ids)", placeholder: "binary_sensor.kitchen_motion, sensor.desk_power>20" }] },
  { key: "keep", title: "What keeps it on", pick: "keep", many: true,
    help: "Sensors that keep an occupied room on but never turn an empty one on: a TV that is playing, a PC drawing power. The room clears once they stop and nothing else sees anyone.",
    fields: [{ key: "keep", label: "Keep-only sensors (entity ids)", placeholder: "media_player.living_room_tv, sensor.pc_power>50" }] },
  { key: "door", title: "Door", pick: "door",
    help: "With a door contact, someone who stays in the room for a while after the door closed has shut themselves in: the room stays occupied, however still they are, until the door opens.",
    fields: [{ key: "door", label: "Door contact (entity id)", placeholder: "binary_sensor.bedroom_door" }] },
  { key: "dark", title: "Light level", pick: "dark",
    help: "The sensor's \"dark\" attribute tells an automation whether lights are needed. A light sensor with a threshold, or any on/off entity that is on when dark. Blank follows the sun.",
    fields: [{ key: "dark", label: "Dark when (entity id, or a number test)", placeholder: "sensor.kitchen_illuminance<20" }] },
  { key: "sleep", title: "Sleep", pick: "sleep_entity",
    help: "An on/off entity that is on while someone sleeps here (a helper, a bed sensor, a sleep schedule). The sensor's \"asleep\" attribute follows it, and the room can take longer to clear meanwhile.",
    fields: [{ key: "sleep_entity", label: "Asleep while on (entity id)", placeholder: "input_boolean.bedroom_asleep" },
             SECS("room_sleep_hold_secs", "Clears after while asleep (s)", 0, 86400, "room_sleep_hold_secs")] },
  { key: "mode", title: "Mode", pick: "mode_entity",
    help: "What the room is being used for, as the sensor's \"mode\" attribute: a dropdown's selected option (\"Movie\"), or the label below while an on/off entity is on.",
    fields: [{ key: "mode_entity", label: "Mode from (entity id)", placeholder: "input_select.theater_mode" },
             { key: "mode_label", label: "Label while an on/off entity is on", placeholder: "Guests" }] },
  { key: "timing", title: "Timing",
    help: "How long the room stays on after the last sign of someone, when a stay counts as extended, and a different clear time once it is. Blank uses the Tuning page's.",
    fields: [SECS("room_hold_secs", "Clears after (s)", 0, 3600, "room_hold_secs"), SECS("room_extended_secs", "Extended after (s)", 30, 86400, "room_extended_secs"),
             SECS("room_extended_hold_secs", "Clears after once extended (s)", 0, 86400, "room_extended_hold_secs")] },
];

/** The states of the entities in a Home Assistant area (their own area, or their device's); Sextant's own sensors and hidden ones left out. */
export function areaEntities(hass, areaId) {
  if (!areaId) return [];
  const devices = hass?.devices || {};
  return Object.values(hass?.entities || {})
    .filter((e) => (e.area_id || devices[e.device_id]?.area_id) === areaId && !e.hidden && e.platform !== "sextant" && !/_sextant_/.test(e.entity_id))
    .map((e) => hass.states?.[e.entity_id]).filter(Boolean);
}

const CLASS = (s) => s.attributes?.device_class;
const WANT = {
  inputs: (s) => s.entity_id.startsWith("binary_sensor.") && ["motion", "occupancy", "presence", "moving"].includes(CLASS(s)),
  keep: (s) => s.entity_id.startsWith("media_player.") || (s.entity_id.startsWith("sensor.") && CLASS(s) === "power"),
  door: (s) => (s.entity_id.startsWith("binary_sensor.") && ["door", "garage_door", "opening"].includes(CLASS(s))) || (s.entity_id.startsWith("cover.") && ["door", "garage"].includes(CLASS(s))),
  dark: (s) => s.entity_id.startsWith("sensor.") && CLASS(s) === "illuminance",
  sleep: (s) => /^(input_boolean|binary_sensor|switch)\./.test(s.entity_id) && /sleep|asleep|bed/.test(s.entity_id) && !WANT.inputs(s),
  mode: (s) => /^(input_select|select|input_boolean)\./.test(s.entity_id),
};
// A number needs a test to mean anything: a starting threshold the user can change.
const TEST = { dark: "<20", keep: ">20" };

/** What a step offers from the area's states: [{value, label}], value being what goes in the field. */
export function suggestions(stepKey, states) {
  const want = WANT[stepKey];
  if (!want) return [];
  return states.filter(want).map((s) => ({
    value: s.entity_id + (s.entity_id.startsWith("sensor.") ? TEST[stepKey] || "" : ""),
    label: s.attributes?.friendly_name || s.entity_id,
  })).sort((a, b) => a.label.localeCompare(b.label));
}

const listOf = (current) => (Array.isArray(current) ? current : String(current ?? "").replace(/\s*(>=|<=|>|<)\s*/g, "$1").split(/[,\s]+/)).map((v) => String(v).trim()).filter(Boolean);
const entityOf = (v) => v.replace(/[<>]=?.*$/, "");

/** Whether a suggestion is already in the field (whatever threshold it was given). */
export function picked(current, value) { return listOf(current).some((v) => entityOf(v) === entityOf(value)); }

/** The field's new value after clicking a suggestion: added or taken out of a list, set or cleared for a single. */
export function toggled(current, value, many) {
  const has = picked(current, value);
  if (!many) return has ? undefined : value;
  const next = has ? listOf(current).filter((v) => entityOf(v) !== entityOf(value)) : [...listOf(current), value];
  return next.length ? next.join(", ") : undefined;
}
