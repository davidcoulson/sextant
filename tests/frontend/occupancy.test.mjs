import test from "node:test";
import assert from "node:assert/strict";
import { occupancyByFloor, spotInRoom } from "../../custom_components/sextant/frontend/sextant-occupancy-data.js";

const st = (state, room, floor, extra = {}) => ({ state, attributes: { room, floor, people: [], pets: [], sources: [], ...extra } });

test("rooms group by floor, top floor first, with people and pets counted", () => {
  const states = {
    "binary_sensor.great_room_sextant_occupancy": st("on", "Great Room", "Ground", { people: ["Jack"], pets: ["Primrose"], sources: ["bluetooth", "media_player"] }),
    "binary_sensor.great_room_sextant_people_occupancy": st("on", "Great Room", "Ground", { people_only: true }),
    "binary_sensor.kitchen_sextant_occupancy": st("on", "Kitchen", "Ground", { pets: ["Cat"] }),
    "binary_sensor.kitchen_sextant_people_occupancy": st("off", "Kitchen", "Ground", { people_only: true }),
    "binary_sensor.renamed": st("on", "Den", "constructor"),
    "binary_sensor.office_sextant_occupancy": st("off", "Office", "Upper"),
    "sensor.other": { state: "1", attributes: {} },
  };
  const out = occupancyByFloor(states, [{ name: "Ground", level: 0 }, { name: "Upper", level: 1 }]);
  assert.deepEqual(out.map((f) => f.name), ["Upper", "Ground", "constructor"]);
  const g = out[1];
  assert.equal(out[2].rooms[0].room, "Den");
  assert.equal(g.people, 1); assert.equal(g.pets, 2);
  assert.equal(g.rooms.find((r) => r.room === "Kitchen").peopleOn, false);
  assert.deepEqual(g.rooms.find((r) => r.room === "Great Room").sources, ["bluetooth", "media_player"]);
});

test("chipDetail finds a pet's spot through its person, and a bare thing through the room's ids", async () => {
  const { chipDetail } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = {
    "person.fry": { state: "home", attributes: { friendly_name: "Fry" } },
    "sensor.fry_sextant_pet_location": { state: "Meg's Cafe", attributes: { room: "Catwalk", spot: "Meg's Cafe", floor: "Second Floor", conf: 0.72, source: "ble", via: "fry_tag" } },
    "sensor.fry_tag_sextant_location": { state: "Meg's Cafe", attributes: { room: "Catwalk", spot: "Meg's Cafe", last_heard: "2026-11-18T18:30:26+00:00" } },
    "sensor.cat_tag_sextant_location": { state: "Kitchen", attributes: { room: "Kitchen", spot: null, floor: "Ground", conf: 0.5 } },
    "person.david": { state: "home", attributes: { friendly_name: "David" } },
    "sensor.david_sextant_person_location": { state: "home", attributes: { room: "unknown", floor: "Ground", source: "wifi", via: "device_tracker.david_phone", access_point: "Hall AP" } },
  };
  const fry = chipDetail(states, "Fry", {});
  assert.equal(fry.spot, "Meg's Cafe"); assert.equal(fry.thing, "fry_tag");
  assert.equal(fry.heardAt, Date.parse("2026-11-18T18:30:26+00:00"));
  const cat = chipDetail(states, "Cat", { Cat: "cat_tag" });
  assert.equal(cat.room, "Kitchen"); assert.equal(cat.spot, null); assert.equal(cat.source, "ble");
  const david = chipDetail(states, "David", {});
  assert.equal(david.thing, null); assert.equal(david.source, "wifi"); assert.equal(david.accessPoint, "Hall AP");
  assert.equal(chipDetail(states, "Nobody", {}), null);
});

test("firstName keeps the first word, capitalised", async () => {
  const { firstName } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  assert.equal(firstName("david coulson"), "David");
  assert.equal(firstName("Eilee"), "Eilee");
  assert.equal(firstName("  meg  "), "Meg");
  assert.equal(firstName(""), "");
});

test("outsideNow lists people and pets whose location is Outside", async () => {
  const { outsideNow } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = {
    "person.primrose": { attributes: { friendly_name: "Primrose" } },
    "sensor.primrose_sextant_pet_location": { state: "Outside", attributes: { kind: "outside", room: "Outside" } },
    "person.david": { attributes: { friendly_name: "David Coulson" } },
    "sensor.david_sextant_person_location": { state: "Kitchen", attributes: { kind: "room", room: "Kitchen" } },
    "person.alex": { attributes: { friendly_name: "Alex" } },
    "sensor.alex_sextant_person_location": { state: "Outside", attributes: { kind: "outside" } },
  };
  assert.deepEqual(outsideNow(states), { people: ["Alex"], pets: ["Primrose"] });
  assert.deepEqual(outsideNow(undefined), { people: [], pets: [] });
});

test("a spot drops its room's name from its front, but never down to nothing", () => {
  assert.equal(spotInRoom("Eilee Bedside Table", "Eilee's Room"), "Bedside Table");
  assert.equal(spotInRoom("Kitchen Island", "Kitchen"), "Island");
  assert.equal(spotInRoom("David Bedside Table", "Master Bedroom", "David"), "Bedside Table");
  assert.equal(spotInRoom("Meg's Cafe", "Catwalk", "Meg"), "Cafe");
  assert.equal(spotInRoom("Eilee Bedside Table", "Eilee's Room", "Eilee"), "Bedside Table");
  assert.equal(spotInRoom("David", "Office", "David"), "David");
  assert.equal(spotInRoom("David Bedside Table", "Master Bedroom", "david_coulson"), "Bedside Table");
  assert.equal(spotInRoom("Michelle Bedside Table", "Master Bedroom", "Michelle Coulson"), "Bedside Table");
  assert.equal(spotInRoom("Desk", "Office"), "Desk");
  assert.equal(spotInRoom("Kitchen", "Kitchen"), "Kitchen");
  assert.equal(spotInRoom("Bed by the Room door", "Eilee's Room"), "Bed by the Room door");
  assert.equal(spotInRoom("Room Divider", "Living Room"), "Room Divider");
  assert.equal(spotInRoom("Living Room Couch", "Living Room"), "Couch");
  assert.equal(spotInRoom("Living Room", "Living Room"), "Living Room");
  assert.equal(spotInRoom("Eilee’s Desk", "Eilee's Room"), "Desk");
  assert.equal(spotInRoom(undefined, "Kitchen"), "");
});

test("chipDetail reports how long it has been there and what tracks it", async () => {
  const { chipDetail } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = {
    "person.david": { attributes: { friendly_name: "David" } },
    "sensor.david_sextant_person_location": { state: "Bedside Table", attributes: { room: "Master Bedroom", spot: "Bedside Table", via: "david_phone", since: 1000, spot_since: 2000 } },
    "person.michelle": { attributes: { friendly_name: "Michelle" } },
    "sensor.michelle_sextant_person_location": { state: "Kitchen", attributes: { room: "Kitchen", spot: null, via: "michelle_watch", since: 1500, spot_since: 3000 } },
    "person.jack": { attributes: { friendly_name: "Jack" } },
    "sensor.jack_sextant_person_location": { state: "home", attributes: { room: "unknown", source: "wifi", via: "device_tracker.jack_phone" } },
    "device_tracker.jack_phone": { attributes: { friendly_name: "Jack's Pixel" } },
  };
  const classes = { david_phone: "phone", michelle_watch: "watch" };
  const d = chipDetail(states, "David", {}, classes);
  assert.equal(d.since, 1000000); assert.equal(d.spotSince, 2000000); assert.equal(d.thingClass, "phone");   // the room's time; the spot has its own
  const m = chipDetail(states, "Michelle", {}, classes);
  assert.equal(m.since, 1500000); assert.equal(m.thingClass, "watch");
  const j = chipDetail(states, "Jack", {}, classes);
  assert.equal(j.since, null); assert.equal(j.thingClass, null); assert.equal(j.tracker, "Jack's Pixel");
  states["sensor.david_sextant_person_location"].attributes.kind = "outside";
  const out = chipDetail(states, "David", {}, classes);
  assert.equal(out.outside, true); assert.equal(out.since, 1000000);   // Outside: since is the spell's, not the spot's
});

test("chipDetail carries the stay-lifted confidence only while the thing is heard", async () => {
  const { chipDetail } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = {
    "person.leela": { attributes: { friendly_name: "Leela" } },
    "sensor.leela_sextant_pet_location": { state: "Morning Room", attributes: { room: "Morning Room", via: "leela_tag", conf: 0.71, settled_conf: 0.86, presence: "here" } },
  };
  const d = chipDetail(states, "Leela", {}, {});
  assert.equal(d.conf, 0.71); assert.equal(d.settled, 0.86);
  states["sensor.leela_sextant_pet_location"].attributes.presence = "quiet";
  // An explicit null on the person sensor is not filled in from the tracker's boost.
  const own = { ...states, "sensor.leela_sextant_pet_location": { state: "Morning Room", attributes: { room: "Morning Room", via: "leela_tag", conf: 0.71, settled_conf: null, presence: "here" } }, "sensor.leela_tag_sextant_location": { state: "x", attributes: { settled_conf: 0.9 } } };
  assert.equal(chipDetail(own, "Leela", {}, {}).settled, null);
  assert.equal(chipDetail(states, "Leela", {}, {}).settled, null);   // a last known place is not fresh evidence
});

test("askStrimmer asks once per connection, again on each reconnect, and swallows HA's refusal", async () => {
  const { askStrimmer, STRIMMER_WANT } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const sent = []; let ready;
  const conn = {
    sendMessagePromise: (m) => { sent.push(m); return Promise.reject(new Error("unknown_command")); },
    addEventListener: (ev, cb) => { if (ev === "ready") ready = cb; },
  };
  askStrimmer(conn); askStrimmer(conn);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { type: "strimmer/want", entity_ids: STRIMMER_WANT });
  ready();
  assert.equal(sent.length, 2);
  askStrimmer(undefined);
  await new Promise((r) => setTimeout(r, 0));   // the rejections must not surface as unhandled
});

test("a room in a mode carries it, and the mode picks an icon", async () => {
  const { modeIcon } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const out = occupancyByFloor({ "binary_sensor.ht": st("on", "Home Theater", "Basement", { mode: "Movie" }), "binary_sensor.den": st("off", "Den", "Basement") }, []);
  const [ht, den] = out[0].rooms;
  assert.equal(ht.mode, "Movie"); assert.equal(den.mode, null);
  assert.equal(modeIcon("Movie"), "mdi:movie-open");
  assert.equal(modeIcon("Gaming"), "mdi:controller");
  assert.equal(modeIcon("Chill"), "mdi:tag");
  assert.equal(modeIcon("Flowerbed"), "mdi:tag");
  assert.equal(modeIcon("Work then Movie"), "mdi:briefcase");
});

test("rooms with activity come first, then empty ones, each alphabetical", () => {
  const out = occupancyByFloor({ "binary_sensor.a": st("off", "Attic", "G"), "binary_sensor.b": st("on", "Study", "G"), "binary_sensor.c": st("off", "Den", "G", { mode: "Movie" }), "binary_sensor.d": st("on", "Hall", "G"), "binary_sensor.e": st("off", "Bath", "G") }, []);
  assert.deepEqual(out[0].rooms.map((r) => r.room), ["Den", "Hall", "Study", "Attic", "Bath"]);
});

test("trackedPeople finds each person's or pet's room and floor sensors", async () => {
  const { trackedPeople } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = {
    "person.michelle": { state: "home", attributes: { friendly_name: "Michelle" } },
    "sensor.michelle_sextant_person_room": { state: "Master Bedroom" },
    "person.meg": { state: "home", attributes: { friendly_name: "Meg" } },
    "sensor.meg_sextant_pet_room": { state: "Catwalk" },
    "person.guest": { state: "not_home", attributes: {} },
  };
  assert.deepEqual(trackedPeople(states), [
    { name: "Meg", pet: true, room: "sensor.meg_sextant_pet_room", floor: "sensor.meg_sextant_pet_floor" },
    { name: "Michelle", pet: false, room: "sensor.michelle_sextant_person_room", floor: "sensor.michelle_sextant_person_floor" },
  ]);
});

test("staysFromHistory joins room and floor changes into stays, one move per cycle", async () => {
  const { staysFromHistory } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const room = [{ s: "Great Room", lu: 100 }, { s: "Great Room", lu: 150 }, { s: "Master Bedroom", lu: 200.5 }, { s: "unavailable", lu: 400 }, { s: "Master Bedroom", lc: 700, lu: 710 }];
  const floor = [{ s: "Ground Floor", lu: 100 }, { s: "Second Floor", lu: 200 }];
  assert.deepEqual(staysFromHistory(room, floor, 1000), [
    { start: 100, end: 200, room: "Great Room", floor: "Ground Floor" },
    { start: 200, end: 400, room: "Master Bedroom", floor: "Second Floor" },
    { start: 400, end: 700, room: null, floor: "Second Floor" },
    { start: 700, end: 1000, room: "Master Bedroom", floor: "Second Floor", ongoing: true },
  ]);
  // A reload: both sensors unavailable for 14 s. No stay of its own; the room either side is one stay.
  const reload = staysFromHistory(
    [{ s: "Eilee's Room", lu: 0 }, { s: "unavailable", lu: 300 }, { s: "Eilee's Room", lu: 314 }, { s: "Kitchen", lu: 400 }, { s: "unavailable", lu: 500 }, { s: "Hall", lu: 513 }],
    [{ s: "Second Floor", lu: 0 }, { s: "unavailable", lu: 300 }, { s: "Second Floor", lu: 314 }, { s: "unavailable", lu: 500 }, { s: "Second Floor", lu: 513 }], 600);
  assert.deepEqual(reload.map((s) => [s.room, s.start, s.end]), [["Eilee's Room", 0, 400], ["Kitchen", 400, 513], ["Hall", 513, 600]]);
  // Only the floor dropping out is a reload too: no "A → A".
  assert.deepEqual(staysFromHistory([{ s: "A", lu: 0 }], [{ s: "F", lu: 0 }, { s: "unavailable", lu: 50 }, { s: "F", lu: 63 }], 100).map((s) => [s.room, s.floor]), [["A", "F"]]);
  // Two short pieces of one long outage (the floor changed in between) are one spell of 150 s, so they stay.
  const long = staysFromHistory([{ s: "A", lu: 0 }, { s: "unavailable", lu: 100 }, { s: "A", lu: 250 }], [{ s: "F", lu: 0 }, { s: "G", lu: 175 }, { s: "F", lu: 250 }], 400);
  assert.deepEqual(long.map((s) => [s.room, s.start]), [["A", 0], [null, 100], [null, 175], ["A", 250]]);
  // Unplaced right now is shown, however short.
  assert.equal(staysFromHistory([{ s: "A", lu: 0 }, { s: "unknown", lu: 95 }], [], 100).at(-1).room, null);
  // A floor change a moment before the room flips back is not a stay of its own.
  assert.deepEqual(staysFromHistory([{ s: "A", lu: 0 }, { s: "A", lu: 10.5 }], [{ s: "F", lu: 0 }, { s: "G", lu: 10 }, { s: "F", lu: 11 }], 50),
    [{ start: 0, end: 50, room: "A", floor: "F", ongoing: true }]);
  assert.deepEqual(staysFromHistory(undefined, undefined, 5), []);
});

test("subjectHistory lists a person's stays, or everyone's in a room or on a floor, newest first", async () => {
  const { subjectHistory } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const people = [
    { name: "Michelle", pet: false, stays: [{ start: 100, end: 200, room: "Great Room", floor: "Ground" }, { start: 200, end: 300, room: null, floor: null }, { start: 300, end: 900, room: "Master Bedroom", floor: "Second" }] },
    { name: "Meg", pet: true, stays: [{ start: 50, end: 400, room: "Master Bedroom", floor: "Second" }, { start: 400, end: 900, room: "Catwalk", floor: "Second" }] },
  ];
  assert.deepEqual(subjectHistory(people, { kind: "person", name: "Michelle" }).map((r) => r.room), ["Master Bedroom", null, "Great Room"]);
  assert.deepEqual(subjectHistory(people, { kind: "room", room: "Master Bedroom", floor: "Second" }).map((r) => [r.name, r.start]), [["Michelle", 300], ["Meg", 50]]);
  assert.deepEqual(subjectHistory(people, { kind: "room", room: "Master Bedroom", floor: "Ground" }), []);
  // Each row knows the room it came from: not placed and the first stay have none.
  assert.deepEqual(subjectHistory(people, { kind: "floor", floor: "Second" }).map((r) => r.from), ["Master Bedroom", null, null]);
  assert.deepEqual(subjectHistory(people, { kind: "person", name: "Michelle" }).map((r) => r.from), [null, "Great Room", null]);
  const halls = [{ name: "Jack", pet: false, stays: [{ start: 0, end: 5, room: "Hall", floor: "Ground" }, { start: 5, end: 9, room: "Hall", floor: "Second" }] }];
  assert.equal(subjectHistory(halls, { kind: "person", name: "Jack" })[0].from, "Hall (Ground)");
  assert.deepEqual(subjectHistory(people, { kind: "floor", floor: "Second" }).map((r) => r.room), ["Catwalk", "Master Bedroom", "Master Bedroom"]);
  assert.equal(subjectHistory(people, { kind: "floor", floor: "Second" }, 1).length, 1);
  // Outside keeps the floor it left from, but is not on that floor.
  const out = [{ name: "Primrose", pet: true, stays: [{ start: 0, end: 10, room: "Outside", floor: "Ground" }, { start: 10, end: 20, room: "Kitchen", floor: "Ground" }] }];
  assert.deepEqual(subjectHistory(out, { kind: "floor", floor: "Ground" }).map((r) => r.room), ["Kitchen"]);
});

test("clockAt says the day when it is not today, and a room carries its since", async () => {
  const { clockAt } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const now = new Date(2026, 10, 27, 9, 0).getTime() / 1000;
  assert.doesNotMatch(clockAt(now - 3600, now), /Yesterday/);
  assert.match(clockAt(now - 86400, now), /^Yesterday /);
  assert.doesNotMatch(clockAt(now - 10 * 3600, now), /Yesterday/);   // 11 PM last night, at 9 AM
  const out = occupancyByFloor({ "binary_sensor.a": st("on", "A", "F", { since: "2026-11-27T08:00:00+00:00" }), "binary_sensor.b": st("off", "B", "F", { since: "garbage" }) }, []);
  assert.equal(out[0].rooms.find((r) => r.room === "A").since, Date.parse("2026-11-27T08:00:00+00:00") / 1000);
  assert.equal(out[0].rooms.find((r) => r.room === "B").since, null);
});

test("confidenceLevel turns a confidence into a word and a crosshairs icon", async () => {
  const { confidenceLevel } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  assert.equal(confidenceLevel(0.77).word, "Confident");
  assert.equal(confidenceLevel(0.7).word, "Confident");
  assert.equal(confidenceLevel(0.53).word, "Likely");
  assert.equal(confidenceLevel(0.1).icon, "mdi:crosshairs-question");
  assert.match(confidenceLevel(0.7).colour, /green/);
  assert.match(confidenceLevel(0.1).colour, /red/);
  assert.equal(confidenceLevel(null), null);
  assert.equal(confidenceLevel(NaN), null);
});

import { joinRepeats, modeStays, modeEntityOf } from "../../custom_components/sextant/frontend/sextant-occupancy-data.js";

test("back-to-back repeats of one move are one row", () => {
  const v = (start, end, name = "Willow", from = "Jack's Room") => ({ name, from, room: "Catwalk", floor: "Second", start, end });
  const rows = joinRepeats([v(500, 560, "Meg", null), v(400, 450), v(200, 260), v(100, 130, "Meg", null), v(50, 60)]);
  assert.deepEqual(rows.map((r) => [r.name, r.count, r.start, r.first, r.total]),
    [["Meg", 1, 500, 500, 60], ["Willow", 2, 400, 200, 110], ["Meg", 1, 100, 100, 30], ["Willow", 1, 50, 50, 10]]);
  // Another room or another "from" is another row.
  assert.equal(joinRepeats([v(400, 450), v(200, 260, "Willow", "Foyer")]).length, 2);
  // A mode row only joins the same mode.
  assert.equal(joinRepeats([{ room: "A", floor: "F", mode: "Sleep", start: 5, end: 6 }, { room: "A", floor: "F", mode: "TV", start: 1, end: 2 }]).length, 2);
});

test("mode spells from a mode entity's history", () => {
  // An on/off entity reads as its label while on; a short unavailable spell does not split it.
  const sleep = modeStays([{ s: "off", lu: 0 }, { s: "on", lu: 100 }, { s: "unavailable", lu: 200 }, { s: "on", lu: 213 }, { s: "off", lu: 900 }], "Sleep", false, 1000);
  assert.deepEqual(sleep.map((s) => [s.mode, s.start, s.end, !!s.ongoing]), [["Sleep", 100, 900, false]]);
  // Still on: ongoing to now. With no label it reads "on".
  assert.deepEqual(modeStays([{ s: "on", lu: 10 }], null, false, 50).map((s) => [s.mode, s.end, s.ongoing]), [["on", 50, true]]);
  // A dropdown's option is the mode as it is, "Idle" too; another entity's own state ("gaming") likewise.
  assert.deepEqual(modeStays([{ s: "Movie", lu: 0 }, { s: "Idle", lu: 60 }], null, true, 100).map((s) => s.mode), ["Movie", "Idle"]);
  assert.deepEqual(modeStays([{ s: "idle", lu: 0 }, { s: "Gaming", lu: 60 }], "X", false, 100).map((s) => s.mode), ["Gaming"]);
  // A long outage ends the mode.
  assert.deepEqual(modeStays([{ s: "on", lu: 0 }, { s: "unavailable", lu: 100 }, { s: "on", lu: 400 }], "Sleep", false, 500).map((s) => [s.start, s.end]), [[0, 100], [400, 500]]);
});

test("review fixes: ongoing row, label spells, recent outage, mode entity", () => {
  const v = (start, end, ongoing) => ({ name: "A", from: "Hall", room: "Kitchen", floor: "G", start, end, ongoing });
  assert.equal(joinRepeats([v(500, 800, true), v(100, 300)]).length, 2);
  // "on" then "playing" are both the label: one spell that runs to now.
  assert.deepEqual(modeStays([{ s: "on", lu: 100 }, { s: "playing", lu: 200 }], "TV", false, 500).map((s) => [s.start, s.end, s.ongoing]), [[100, 500, true]]);
  // Unavailable 20 s ago: still in the mode.
  assert.deepEqual(modeStays([{ s: "on", lu: 100 }, { s: "unavailable", lu: 480 }], "Sleep", false, 500).map((s) => [s.mode, s.end, !!s.ongoing]), [["Sleep", 500, true]]);
  assert.equal(modeEntityOf(["bogus", "input_select.theater"]), "input_select.theater");
  assert.equal(modeEntityOf("binary_sensor.a_asleep, switch.b"), "binary_sensor.a_asleep");
  assert.equal(modeEntityOf(null), null);
});

test("roomChip lists people before pets with their person pictures; lastOccupants finds the newest names", async () => {
  const { roomChip, fmtFor, lastOccupants } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = {
    "binary_sensor.kitchen_sextant_occupancy": { state: "on", attributes: { room: "Kitchen", people: ["Michelle Bauer"], pets: ["Socks"], mode: "Cooking", since: "2026-11-27T10:00:00+00:00" } },
    "person.michelle_bauer": { state: "home", attributes: { entity_picture: "/api/image/m" } },
  };
  const r = roomChip(states, "binary_sensor.kitchen_sextant_occupancy");
  assert.deepEqual(r.faces, [{ name: "Michelle Bauer", pet: false, picture: "/api/image/m", activity: null }, { name: "Socks", pet: true, picture: null, sensor: "sensor.socks_sextant_pet_location", activity: null }]);
  assert.equal(r.on, true); assert.equal(r.mode, "Cooking"); assert.equal(r.since, Date.parse("2026-11-27T10:00:00Z") / 1000);
  assert.equal(roomChip(states, "binary_sensor.nope"), null);
  assert.deepEqual([fmtFor(59), fmtFor(720), fmtFor(5280), fmtFor(3 * 86400)], ["0m", "12m", "1h 28m", "3d"]);
  assert.deepEqual(lastOccupants([{ a: { people: ["Jack"] } }, { a: { people: ["Michelle"], pets: ["Meg"] } }, { a: { people: [], pets: [] } }]), ["Michelle", "Meg"]);
  assert.deepEqual(lastOccupants(undefined), []);
});

test("the room chip marks a pet whose motion collar says resting or moving, from its pet sensor", async () => {
  const { roomChip } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = {
    "binary_sensor.foyer_sextant_occupancy": { state: "on", attributes: { room: "Foyer", people: ["Michelle"], pets: ["Leela", "Socks", "Meg"] } },
    "sensor.leela_sextant_pet_location": { state: "Foyer", attributes: { activity: "still", source: "ble" } },
    "sensor.socks_sextant_pet_location": { state: "Foyer", attributes: { activity: "moving" } },
    "sensor.meg_sextant_pet_location": { state: "Foyer", attributes: { activity: "still", source: "held" } },  // unheard: stale
  };
  const faces = roomChip(states, "binary_sensor.foyer_sextant_occupancy").faces;
  assert.deepEqual(faces.map((f) => f.activity?.label ?? null), [null, "Resting", "Moving", null]);
});

test("the room chip asks Strimmer for the person entities it finds at runtime", async () => {
  // The card needs a DOM to load, so this checks its source: the ask must run on every hass update.
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../../custom_components/sextant/frontend/sextant-room-chip.js", import.meta.url), "utf8");
  assert.match(src, /import \{[^}]*\baskStrimmer\b[^}]*\} from "\.\/sextant-occupancy-data\.js"/);
  assert.match(src, /updated\(changed\) \{[^}]*if \(changed\.has\("hass"\)\) askStrimmer\(this\.hass\?\.connection\);/);
});

test("roomChip finds an accented name's person entity the way Home Assistant slugs it", async () => {
  const { roomChip } = await import("../../custom_components/sextant/frontend/sextant-occupancy-data.js");
  const states = { "binary_sensor.r": { state: "on", attributes: { people: ["José Silva"] } }, "person.jose_silva": { attributes: { entity_picture: "/p" } } };
  assert.equal(roomChip(states, "binary_sensor.r").faces[0].picture, "/p");
});
