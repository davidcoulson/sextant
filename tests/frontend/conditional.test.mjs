// The Sextant conditional card's model, on the shapes Sextant's sensors really have.
import { test } from "node:test";
import assert from "node:assert/strict";
import { personForUser, placeOf, shows, testsPlace, choices } from "../../custom_components/sextant/frontend/sextant-conditional.js";

const st = (state, attributes) => ({ state, attributes });
const states = {
  "person.david_coulson": st("home", { user_id: "u-david", friendly_name: "David Coulson" }),
  "person.michelle_bauer": st("home", { user_id: "u-michelle", friendly_name: "Michelle Bauer" }),
  "person.sherry_wayne": st("not_home", { friendly_name: "Sherry Wayne" }),
  "person.meg": st("home", { friendly_name: "Meg" }),
  "sensor.david_coulson_sextant_person_location": st("Home Theater", { kind: "room", room: "Home Theater", floor: "Basement", presence: "here" }),
  "sensor.michelle_bauer_sextant_person_location": st("away", { kind: "zone", room: "unknown", floor: "unknown", presence: "away" }),
  "sensor.meg_sextant_pet_location": st("Meg's Cafe", { kind: "spot", room: "Catwalk", floor: "Second Floor" }),
  "binary_sensor.kitchen_sextant_occupancy": st("off", { room: "Kitchen", floor: "Ground Floor" }),
  "binary_sensor.home_theater_sextant_occupancy": st("on", { room: "Home Theater", floor: "Basement" }),
};

test("the viewer's person comes from the user id", () => {
  assert.equal(personForUser(states, "u-michelle"), "person.michelle_bauer");
  assert.equal(personForUser(states, "u-nobody"), null);
  assert.equal(personForUser(states, undefined), null);
});

test("a place from the location sensor; away and missing have none", () => {
  assert.deepEqual(placeOf(states, "person.david_coulson"), { room: "Home Theater", floor: "Basement" });
  assert.deepEqual(placeOf(states, "person.meg"), { room: "Catwalk", floor: "Second Floor" });
  assert.deepEqual(placeOf(states, "person.michelle_bauer"), { room: null, floor: null });
  assert.deepEqual(placeOf(states, "person.sherry_wayne"), { room: null, floor: null });
  assert.deepEqual(placeOf(states, null), { room: null, floor: null });
});

test("rooms or floors match, ignoring case; users narrow it", () => {
  const here = { userId: "u-david", room: "Home Theater", floor: "Basement" };
  assert.equal(shows({ rooms: ["home theater"] }, here), true);
  assert.equal(shows({ rooms: ["Kitchen"] }, here), false);
  assert.equal(shows({ rooms: ["Kitchen"], floors: ["Basement"] }, here), true, "room or floor");
  assert.equal(shows({ floors: "Basement" }, here), true, "a single value works too");
  assert.equal(shows({ users: ["u-michelle"] }, here), false);
  assert.equal(shows({ users: ["u-david"], rooms: ["Home Theater"] }, here), true);
  assert.equal(shows({}, here), true, "no conditions: always");
  assert.equal(shows({ rooms: ["Kitchen"] }, { userId: "u-david", room: null, floor: null }), false, "away matches no room");
  assert.equal(testsPlace({ users: ["u-david"], rooms: [] }), false);
  assert.equal(testsPlace({ floors: ["Basement"] }), true);
});

test("editor choices: rooms and floors from room sensors, users from linked people", () => {
  const c = choices(states);
  assert.deepEqual(c.rooms.map((o) => o.value), ["Home Theater", "Kitchen"]);
  assert.deepEqual(c.floors.map((o) => o.value), ["Basement", "Ground Floor"]);
  assert.deepEqual(c.users, [{ value: "u-david", label: "David Coulson" }, { value: "u-michelle", label: "Michelle Bauer" }]);
});
