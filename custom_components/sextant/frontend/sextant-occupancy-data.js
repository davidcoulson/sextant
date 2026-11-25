/** Room occupancy grouped by floor, from the room sensors' states. No DOM: the tab and the tests share it. */
import { sortFloors } from "./sextant-floors.js";

export const SOURCE_LABEL = { bluetooth: "Bluetooth", radar: "Radar", media_player: "Media playing", sensor: "Sensor", forced: "Forced on", door: "Door held", restored: "Carried over restart", keep: "Kept on by a sensor", hold: "Holding" };
export const SOURCE_ICON = { bluetooth: "mdi:bluetooth", radar: "mdi:radar", media_player: "mdi:television-play", sensor: "mdi:motion-sensor", forced: "mdi:toggle-switch", door: "mdi:door", restored: "mdi:restart", keep: "mdi:pin", hold: "mdi:timer-sand" };

// A room's mode (Movie, Gaming, ...) picks its icon by its first word that starts like one; anything else gets a tag.
const MODE_ICONS = [[/^(movie|film|cinema|theat)/, "mdi:movie-open"], [/^(tv|watch)/, "mdi:television-play"], [/^gam/, "mdi:controller"],
  [/^(music|party|listen)/, "mdi:music"], [/^(sleep|night|bed)/, "mdi:sleep"], [/^read/, "mdi:book-open-variant"], [/^(work|meeting|call|office)/, "mdi:briefcase"],
  [/^(cook|dinner|meal|bak)/, "mdi:silverware-fork-knife"], [/^(away|vacation)/, "mdi:airplane"], [/^guest/, "mdi:account-multiple"]];
export function modeIcon(mode) {
  for (const w of String(mode).toLowerCase().split(/[^a-z0-9]+/)) { const hit = MODE_ICONS.find(([re]) => re.test(w)); if (hit) return hit[1]; }
  return "mdi:tag";
}

export function occupancyByFloor(states, planFloors) {
  const rooms = new Map(), people = new Map();
  for (const [id, s] of Object.entries(states || {})) {
    const a = s?.attributes || {};
    if (!id.startsWith("binary_sensor.") || a.room == null || a.floor == null) continue;
    const key = `${a.floor}\u0000${a.room}`;
    if (a.people_only) people.set(key, s.state === "on");
    else rooms.set(key, { room: a.room, floor: a.floor, on: s.state === "on", people: a.people || [], pets: a.pets || [], things: a.things || [], ids: a.ids || {}, sources: a.sources || [], mode: a.mode || null });
  }
  const byFloor = new Map();
  for (const [key, r] of rooms) {
    r.peopleOn = people.get(key) ?? r.people.length > 0;
    if (!byFloor.has(r.floor)) byFloor.set(r.floor, []);
    byFloor.get(r.floor).push(r);
  }
  const names = sortFloors(planFloors).map((f) => f.name);
  for (const n of byFloor.keys()) if (!names.includes(n)) names.push(n);
  return names.filter((n) => byFloor.has(n)).map((name) => {
    const list = byFloor.get(name).sort((a, b) => a.room.localeCompare(b.room));
    return { name, rooms: list, people: new Set(list.flatMap((r) => r.people)).size, pets: new Set(list.flatMap((r) => r.pets)).size };
  });
}

export const WHERE_SOURCE = { ble: "Bluetooth", wifi: "Wi-Fi", gps: "GPS", held: "Bluetooth (held)", none: "None" };
export const WHERE_ICON = { ble: "mdi:bluetooth", wifi: "mdi:wifi", gps: "mdi:crosshairs-gps", held: "mdi:bluetooth-off", none: "mdi:help-circle-outline" };

/** People and pets whose Sextant location is Outside (beyond every room, still at home). */
// shortcut: only pets with a person.* entity are listed; a tag-only pet outside shows nowhere. Add layout thing_classes if one appears.
export function outsideNow(states) {
  states = states || {};
  const people = [], pets = [];
  for (const [id, s] of Object.entries(states)) {
    if (!id.startsWith("person.")) continue;
    const slug = id.slice(7);
    const pet = states[`sensor.${slug}_sextant_pet_location`];
    const loc = states[`sensor.${slug}_sextant_person_location`] || pet;
    if (loc?.attributes?.kind === "outside") (loc === pet ? pets : people).push(s.attributes?.friendly_name || slug);
  }
  return { people: people.sort(), pets: pets.sort() };
}

/** Where a chip's person, pet or thing is, from its location sensors; null when it has none.
 *  ``ids`` is the room sensor's {display name: thing slug}; a person (or a pet that is a
 *  person) is found by the friendly name the room sensor listed them under. ``classes`` is the
 *  layout's thing_classes, for the class of the thing doing the tracking. */
export function chipDetail(states, name, ids, classes) {
  states = states || {};
  const person = Object.keys(states).find((id) => id.startsWith("person.") && (states[id]?.attributes?.friendly_name || id.slice(7)) === name);
  const slug = person?.slice(7);
  const loc = slug ? states[`sensor.${slug}_sextant_person_location`] || states[`sensor.${slug}_sextant_pet_location`] : null;
  const via = loc ? loc.attributes?.via : ids?.[name];
  const thing = via && !String(via).includes(".") ? via : null;   // a Wi-Fi via is a device_tracker, not a thing
  const tloc = thing ? states[`sensor.${thing}_sextant_location`] : null;
  const s = loc || tloc;
  if (!s) return null;
  const a = s.attributes || {}, t = tloc?.attributes || {};
  const heard = a.last_heard || t.last_heard;
  const spot = a.spot && a.spot !== "unknown" ? a.spot : null;
  const outside = a.kind === "outside";
  // Outside, since is when the spell outside began (the thing's own sensor says so too).
  const since = (spot && !outside ? a.spot_since ?? t.spot_since : null) ?? a.since ?? t.since;
  const tracker = via && String(via).includes(".") ? states[via]?.attributes?.friendly_name || via : null;
  return {
    outside, thing, thingClass: thing ? classes?.[thing] || null : null, tracker,
    since: typeof since === "number" ? since * 1000 : null,
    room: a.room, spot, floor: a.floor, presence: a.presence,
    conf: a.conf ?? t.conf ?? null, source: a.source || "ble",
    // conf lifted by the stay; only while heard, a quiet thing's last word is no fresh evidence.
    settled: a.presence === "here" && !outside ? a.settled_conf ?? null : null,
    accessPoint: a.access_point || null, gpsAccuracy: a.gps_accuracy ?? null,
    heardAt: heard ? Date.parse(heard) : null,
  };
}

/** A person's chip label: the first word of their name, capitalised ("david coulson" -> "David"). */
export const firstName = (name) => { const w = String(name ?? "").trim().split(/\s+/)[0]; return w ? w[0].toUpperCase() + w.slice(1) : String(name ?? ""); };

// A spot named after its room or the one in it ("Eilee Bedside Table" in Eilee's Room, "David Bedside Table"
// for David) drops that name from its front: its words in order ("Room Divider" in Living Room stays),
// room first, then the person, and never the whole spot.
export function spotInRoom(spot, room, who) {
  const norm = (w) => w.toLowerCase().replace(/['’]s$/, "");
  const split = (s) => String(s ?? "").split(/[\s_]+/).filter(Boolean);
  let words = split(spot);
  for (const name of [room, who]) {
    const lead = split(name).map(norm);
    let i = 0;
    while (i < words.length && i < lead.length && norm(words[i]) === lead[i]) i++;
    if (i < words.length) words = words.slice(i);
  }
  return words.join(" ");
}

// The pages read Sextant's entities straight from hass.states, so a trimming proxy (Strimmer) that
// only forwards what dashboards name would hide them. Ask it for them on each connection; without
// Strimmer, Home Assistant answers unknown_command, which is ignored.
export const STRIMMER_WANT = ["*_sextant_*", "person.*"];
const askedConns = new WeakSet();
export function askStrimmer(conn) {
  if (!conn?.sendMessagePromise || askedConns.has(conn)) return;
  askedConns.add(conn);
  const ask = () => conn.sendMessagePromise({ type: "strimmer/want", entity_ids: STRIMMER_WANT }).catch(() => {});
  ask();
  conn.addEventListener?.("ready", ask);
}
