// The "where is everyone" card's model, on the shapes Sextant's sensors really have.
import { test } from "node:test";
import assert from "node:assert/strict";
import { confLevel, fmtStay, whereRows, groupRooms, stripChips, withPerson, preciseWhere } from "../../custom_components/sextant/frontend/sextant-where.js";
import { entityOptions } from "../../custom_components/sextant/frontend/sextant-ha-editors.js";

const NOW = 1795775000;
const loc = (state, attrs) => ({ state, attributes: attrs });
const states = {
  "sensor.david_coulson_sextant_person_location": loc("Peninsula", { kind: "spot", room: "Kitchen", spot: "Peninsula", floor: "Ground Floor", conf: 0.575, since: NOW - 2520, via_class: "phone", source: "ble", presence: "here", friendly_name: "David Coulson Location" }),
  "person.david_coulson": loc("home", { friendly_name: "David Coulson", entity_picture: "/api/image/serve/x/512x512" }),
  "sensor.sherry_wayne_sextant_person_location": loc("away", { kind: "zone", room: "unknown", spot: null, floor: "unknown", zone: "not_home", presence: "away", via_class: null }),
  "sensor.meg_sextant_pet_location": loc("Meg's Cafe", { kind: "spot", room: "Catwalk", spot: "Meg's Cafe", floor: "Second Floor", conf: 0.9, since: NOW - 600, via_class: "cat", friendly_name: "Meg Location" }),
  "sensor.fry_sextant_pet_location": loc("Great Room", { kind: "room", room: "Great Room", floor: "Ground Floor", conf: 0.3, since: NOW - 7200, via_class: "cat" }),
  "sensor.leela_sextant_pet_location": loc("Couch", { kind: "spot", room: "Great Room", spot: "Couch", floor: "Ground Floor", conf: 0.8, since: NOW - 60, via_class: "cat" }),
  "binary_sensor.great_room_sextant_occupancy": loc("on", { room: "Great Room", mode: "TV" }),
};

test("confidence bands match the Occupancy page", () => {
  assert.equal(confLevel(0.7).key, "confident");
  assert.equal(confLevel(0.4).key, "likely");
  assert.equal(confLevel(0.39).key, "unsure");
  assert.equal(confLevel(undefined), null);
});

test("stays read short", () => {
  assert.equal(fmtStay(30), "now");
  assert.equal(fmtStay(42 * 60), "42m");
  assert.equal(fmtStay(185 * 60), "3h 5m");
  assert.equal(fmtStay(185 * 60, true), "3h");
  assert.equal(fmtStay(52 * 3600), "2d 4h");
  assert.equal(fmtStay(null), "");
});

test("rows: room first, spot apart, name and picture from the person", () => {
  const [d, s, m] = whereRows(states, [
    { entity: "sensor.david_coulson_sextant_person_location", person: "person.david_coulson" },
    "sensor.sherry_wayne_sextant_person_location",
    { entity: "sensor.meg_sextant_pet_location", name: "Meg" },
  ], NOW);
  assert.deepEqual([d.name, d.room, d.spot, d.floor, d.stay, d.level.key, d.via, d.pet], ["David", "Kitchen", "Peninsula", "Ground Floor", 2520, "likely", "phone", false]);
  assert.equal(d.picture, "/api/image/serve/x/512x512");
  assert.deepEqual([s.name, s.where, s.away, s.room, s.floor, s.level], ["Sherry", "Away", true, null, null, null]);
  assert.deepEqual([m.name, m.pet, m.room, m.spot], ["Meg", true, "Catwalk", "Meg's Cafe"]);
});

test("a missing entity shows as unavailable rather than vanishing", () => {
  const [r] = whereRows({}, ["sensor.gone_sextant_person_location"], NOW);
  assert.equal(r.where, "Unavailable");
});

test("rooms group the household and carry the room's mode", () => {
  const rows = whereRows(states, ["sensor.fry_sextant_pet_location", "sensor.meg_sextant_pet_location", "sensor.leela_sextant_pet_location"], NOW);
  const g = groupRooms(rows, [states["binary_sensor.great_room_sextant_occupancy"]]);
  assert.deepEqual(g.map((x) => [x.room, x.rows.length, x.mode]), [["Great Room", 2, "TV"], ["Catwalk", 1, null]]);
});

test("rooms leave out away people: away is not a room", () => {
  const rows = whereRows(states, ["sensor.sherry_wayne_sextant_person_location", "sensor.meg_sextant_pet_location"], NOW);
  assert.deepEqual(groupRooms(rows).map((x) => x.room), ["Catwalk"]);
});

test("the strip folds same-class pets on a floor, people stay single", () => {
  const rows = whereRows(states, ["sensor.david_coulson_sextant_person_location", "sensor.fry_sextant_pet_location", "sensor.meg_sextant_pet_location", "sensor.leela_sextant_pet_location"], NOW);
  const chips = stripChips(rows);
  assert.deepEqual(chips.map((c) => c.kind === "one" ? c.row.name : `${c.rows.length} ${c.cls} ${c.floor}`), ["David", "2 cat Ground Floor", "Meg"]);
});

test("Strimmer: the model reads only the entities the config names", () => {
  // Behind Strimmer a dashboard gets just the entity ids its config names; an id the card
  // worked out for itself would read as missing. So no lookups beyond the config.
  const read = new Set();
  const spy = new Proxy(states, { get: (t, k) => { read.add(k); return t[k]; }, ownKeys: () => { throw new Error("scanned hass.states"); } });
  const entities = [{ entity: "sensor.david_coulson_sextant_person_location", person: "person.david_coulson" }, "sensor.fry_sextant_pet_location"];
  groupRooms(whereRows(spy, entities, NOW), []);
  assert.deepEqual([...read].sort(), ["person.david_coulson", "sensor.david_coulson_sextant_person_location", "sensor.fry_sextant_pet_location"]);
});

test("editor: a sensor picked in the editor brings its person, when there is one", () => {
  assert.deepEqual(withPerson(states, "sensor.david_coulson_sextant_person_location"), { entity: "sensor.david_coulson_sextant_person_location", person: "person.david_coulson" });
  assert.equal(withPerson(states, "sensor.meg_sextant_pet_location"), "sensor.meg_sextant_pet_location");
  assert.equal(withPerson(states, "sensor.other"), "sensor.other");
});

test("editor: options by label, and configured ids kept even when missing", () => {
  const opts = entityOptions(states, (id) => /_sextant_pet_location$/.test(id), (id, s) => s.attributes.friendly_name || id, ["sensor.gone_sextant_pet_location"]);
  assert.deepEqual(opts.map((o) => o.label), ["Meg Location", "sensor.fry_sextant_pet_location", "sensor.gone_sextant_pet_location", "sensor.leela_sextant_pet_location"]);
});

test("away: the phone's town, and what they're doing when on the move", () => {
  const away = loc("away", { kind: "zone", zone: "not_home", presence: "away", tracker: "device_tracker.mi_phone", source: "gps" });
  const st = {
    "sensor.mi_sextant_person_location": away,
    "sensor.mi_phone_activity": loc("Automotive", {}),
    "sensor.mi_phone_geocoded_location": loc("6800 Pearl Rd", { Locality: "Middleburg Heights", "Administrative Area": "OH" }),
    "sensor.work_sextant_person_location": loc("away", { kind: "zone", zone: "work", presence: "away" }),
  };
  const e = { entity: "sensor.mi_sextant_person_location", activity: "sensor.mi_phone_activity", place: "sensor.mi_phone_geocoded_location" };
  const [d, z] = whereRows(st, [e, { ...e, entity: "sensor.work_sextant_person_location" }], NOW);
  assert.deepEqual([d.where, d.moving.icon, d.zone], ["Driving near Middleburg Heights, OH", "mdi:car-hatchback", false]);
  assert.deepEqual([z.where, z.zone], ["Work", true]);  // a named zone wins over the town
  st["sensor.mi_phone_activity"] = loc("Stationary", {});
  assert.deepEqual(whereRows(st, [e], NOW).map((r) => [r.where, r.moving]), [["Middleburg Heights, OH", null]]);
  st["sensor.mi_phone_geocoded_location"] = loc("unavailable", { Locality: "Cleveland", "Administrative Area": "OH" });
  st["sensor.mi_phone_activity"] = loc("Walking", {});
  assert.equal(whereRows(st, [e], NOW)[0].where, "Walking");
  assert.equal(whereRows(st, ["sensor.mi_sextant_person_location"], NOW)[0].where, "Away");
});

test("editor: a picked person brings their phone's activity and town sensors", () => {
  const st = { ...states, "sensor.david_coulson_sextant_person_location": loc("x", { tracker: "device_tracker.d_phone" }) };
  const reg = { "device_tracker.d_phone": { device_id: "D" }, "sensor.d_phone_sleep_activity": { device_id: "D" }, "sensor.d_phone_activity": { device_id: "D" }, "sensor.d_phone_geocoded_location": { device_id: "D" }, "sensor.other_activity": { device_id: "E" } };
  assert.deepEqual(withPerson(st, "sensor.david_coulson_sextant_person_location", reg), {
    entity: "sensor.david_coulson_sextant_person_location", person: "person.david_coulson",
    activity: "sensor.d_phone_activity", place: "sensor.d_phone_geocoded_location",
  });
});

test("Life360: a tracker gives driving and its place or address", () => {
  const st = {
    "sensor.j_sextant_person_location": loc("away", { kind: "zone", zone: "not_home", presence: "away", tracker: "device_tracker.j" }),
    "device_tracker.j": loc("not_home", { driving: true, address: "Pearl Road, Ohio", place: null }),
  };
  const e = { entity: "sensor.j_sextant_person_location", activity: "device_tracker.j", place: "device_tracker.j" };
  assert.equal(whereRows(st, [e], NOW)[0].where, "Driving near Pearl Road, Ohio");
  st["device_tracker.j"] = loc("not_home", { driving: false, address: "Main St, Ohio", place: "School" });
  assert.deepEqual(whereRows(st, [e], NOW).map((r) => [r.where, r.moving]), [["School", null]]);
  // The editor: no Companion app sensors on the Life360 device, so the tracker fills both keys.
  assert.deepEqual(withPerson(st, "sensor.j_sextant_person_location", { "device_tracker.j": { device_id: "L" } }),
    { entity: "sensor.j_sextant_person_location", activity: "device_tracker.j", place: "device_tracker.j" });
  // Life360 still at home while Sextant says away: the street, not the home place; a dead tracker's flag is stale.
  st["device_tracker.j"] = loc("home", { driving: false, address: "Silver Tree Trail, Ohio", place: "Home (Bauer Coulson)" });
  assert.equal(whereRows(st, [e], NOW)[0].where, "Silver Tree Trail, Ohio");
  st["device_tracker.j"] = loc("unavailable", { driving: true, address: "Pearl Road, Ohio" });
  assert.equal(whereRows(st, [e], NOW)[0].where, "Away");
});

test("precise: spot, else room, else floor, else Home; away and unavailable keep their line", () => {
  assert.equal(preciseWhere({ where: "Great Room", room: "Great Room", spot: "Couch", floor: "Ground Floor" }), "Couch");
  assert.equal(preciseWhere({ where: "Great Room", room: "Great Room", spot: null, floor: "Ground Floor" }), "Great Room");
  assert.equal(preciseWhere({ where: "Home", room: null, spot: null, floor: "Ground Floor" }), "Ground Floor");
  assert.equal(preciseWhere({ where: "Quiet", room: null, spot: null, floor: null }), "Home");
  assert.equal(preciseWhere({ where: "Driving near Avon, OH", away: true, room: null, spot: null, floor: null }), "Driving near Avon, OH");
  assert.equal(preciseWhere({ where: "Unavailable", room: null, spot: null, floor: null }), "Unavailable");
});

test("away: the town on its own for the tile headline, and time away from the sensor's last change", () => {
  const st = {
    "sensor.mi_sextant_person_location": { ...loc("away", { kind: "zone", zone: "not_home", presence: "away" }), last_changed: new Date((NOW - 3600) * 1000).toISOString() },
    "sensor.mi_phone_activity": loc("Walking", {}),
    "sensor.mi_phone_geocoded_location": loc("6800 Pearl Rd", { Locality: "Middleburg Heights", "Administrative Area": "OH" }),
    "sensor.work_sextant_person_location": loc("away", { kind: "zone", zone: "work", presence: "away" }),
  };
  const e = { entity: "sensor.mi_sextant_person_location", activity: "sensor.mi_phone_activity", place: "sensor.mi_phone_geocoded_location" };
  const [d, z] = whereRows(st, [e, { entity: "sensor.work_sextant_person_location" }], NOW);
  assert.deepEqual([d.place, d.where, d.stay], ["Middleburg Heights, OH", "Walking near Middleburg Heights, OH", 3600]);
  assert.deepEqual([z.place, z.stay], [null, null]);  // a zone is the place itself; no last_changed, no time
  st["sensor.mi_phone_geocoded_location"] = loc("unavailable", {});
  assert.equal(whereRows(st, [e], NOW)[0].place, null);
});
