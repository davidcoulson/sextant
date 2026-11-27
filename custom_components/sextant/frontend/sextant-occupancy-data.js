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

/** A room is active when it is on or in a mode. */
export const isActive = (r) => Boolean(r.on || r.mode);

export function occupancyByFloor(states, planFloors) {
  const rooms = new Map(), people = new Map();
  for (const [id, s] of Object.entries(states || {})) {
    const a = s?.attributes || {};
    if (!id.startsWith("binary_sensor.") || a.room == null || a.floor == null) continue;
    const key = `${a.floor}\u0000${a.room}`;
    if (a.people_only) people.set(key, s.state === "on");
    else rooms.set(key, { room: a.room, floor: a.floor, on: s.state === "on", people: a.people || [], pets: a.pets || [], things: a.things || [], ids: a.ids || {}, sources: a.sources || [], mode: a.mode || null, since: Date.parse(a.since) / 1000 || null });   // ISO; null when missing or unreadable
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
    // Rooms with something going on first, then the empty ones; each group alphabetical.
    const list = byFloor.get(name).sort((a, b) => (isActive(b) - isActive(a)) || a.room.localeCompare(b.room));
    return { name, rooms: list, people: new Set(list.flatMap((r) => r.people)).size, pets: new Set(list.flatMap((r) => r.pets)).size };
  });
}

export const WHERE_SOURCE = { ble: "Bluetooth", wifi: "Wi-Fi", gps: "GPS", held: "Bluetooth (held)", none: "None" };
export const WHERE_ICON = { ble: "mdi:bluetooth", wifi: "mdi:wifi", gps: "mdi:map-marker-radius", held: "mdi:bluetooth-off", none: "mdi:help-circle-outline" };

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

/** The people and pets with Sextant room sensors: {name, pet, room, floor} (entity ids), by name. */
export function trackedPeople(states) {
  states = states || {};
  const out = [];
  for (const [id, s] of Object.entries(states)) {
    if (!id.startsWith("person.")) continue;
    const slug = id.slice(7);
    for (const kind of ["person", "pet"]) {
      const room = `sensor.${slug}_sextant_${kind}_room`;
      if (states[room]) { out.push({ name: s.attributes?.friendly_name || slug, pet: kind === "pet", room, floor: `sensor.${slug}_sextant_${kind}_floor` }); break; }
    }
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

// What a room or floor sensor reads while nobody knows where its person is.
const NOWHERE = new Set(["unknown", "unavailable", "", "none"]);
const changes = (rows) => (rows || []).map((r) => ({ t: r.lc ?? r.lu, v: NOWHERE.has(String(r.s ?? "").toLowerCase()) ? null : r.s })).filter((r) => typeof r.t === "number");

/** One person's stays, [{start, end, room, floor}] oldest first, from Home Assistant's history
 *  (history/history_during_period, compressed rows {s, lu, lc?}) of their room and floor sensors.
 *  A stay is a run with the same room on the same floor; room null is "not placed". The last
 *  stay runs to ``now``. */
export function staysFromHistory(roomRows, floorRows, now) {
  const ev = [...changes(roomRows).map((r) => ({ ...r, k: "room" })), ...changes(floorRows).map((r) => ({ ...r, k: "floor" }))].sort((a, b) => a.t - b.t);
  const stays = [];
  const cur = { room: null, floor: null };
  for (const e of ev) {
    cur[e.k] = e.v;
    const last = stays[stays.length - 1];
    if (last && last.room === cur.room && last.floor === cur.floor) continue;
    // The room and floor sensors change in the same cycle, a moment apart: one move, not two.
    if (last && e.t - last.start < 2) {
      Object.assign(last, cur);
      const prev = stays[stays.length - 2];
      if (prev && prev.room === last.room && prev.floor === last.floor) { stays.pop(); prev.end = now; }
      continue;
    }
    if (last) last.end = e.t;
    stays.push({ start: e.t, end: now, room: cur.room, floor: cur.floor });
  }
  // A short spell with the room or the floor missing is Sextant reloading or restarting (its sensors read
  // unavailable for a few seconds), not a move: drop it, give its time to the stay before, and join the same
  // room either side. A run of such stays counts as one spell, and the current state stays however short.
  const kept = [];
  const keep = (s) => {
    const last = kept[kept.length - 1];
    if (last && last.room === s.room && last.floor === s.floor) { last.end = s.end; return; }
    if (last) last.end = s.start;
    kept.push(s);
  };
  const missing = (s) => s.room === null || s.floor === null;
  for (let i = 0; i < stays.length;) {
    if (!missing(stays[i])) { keep(stays[i++]); continue; }
    let j = i;
    while (j < stays.length && missing(stays[j])) j++;
    if (j === stays.length || stays[j - 1].end - stays[i].start >= BLIP_SECS) stays.slice(i, j).forEach(keep);
    i = j;
  }
  // The last stay is still going: the sheet shows it as "now" and counts it to the moment it draws.
  if (kept.length) kept[kept.length - 1].ongoing = true;
  return kept;
}
const BLIP_SECS = 120;

/** The history rows for one subject, newest first: a person's or pet's own stays
 *  ({kind: "person", name}), everyone's stays in a room ({kind: "room", room, floor}),
 *  or on a floor ({kind: "floor", floor}). ``people`` is [{name, pet, stays}]. A room or
 *  floor lists only placed stays; a person's list keeps "not placed" ones. */
export function subjectHistory(people, subject, limit = 100) {
  const rows = [];
  for (const p of people || []) {
    if (subject.kind === "person" && p.name !== subject.name) continue;
    (p.stays || []).forEach((s, i) => {
      if (subject.kind === "room" && !(s.room === subject.room && s.floor === subject.floor)) return;
      // Outside keeps the floor it left from, but is on no floor.
      if (subject.kind === "floor" && !(s.room && s.room !== "Outside" && s.floor === subject.floor)) return;
      // ``from``: the room they came from, for "Great Room → Kitchen"; null when unplaced or the first stay.
      // The same room name on another floor says which floor, or it would read "Hall → Hall".
      const prev = p.stays[i - 1];
      const from = !prev?.room ? null : prev.room === s.room && prev.floor ? `${prev.room} (${prev.floor})` : prev.room;
      rows.push({ name: p.name, pet: p.pet, from, ...s });
    });
  }
  return rows.sort((a, b) => b.start - a.start || a.name.localeCompare(b.name)).slice(0, limit);
}

/** A time of day for a history row. Within the last 24 hours a clock time names one moment, so it needs no
 *  day ("11:50 PM" at 6 AM is last night); older (a stay begun before the window) says "Yesterday" or the weekday. */
export function clockAt(t, now = Date.now() / 1000) {
  const d = new Date(t * 1000), n = new Date(now * 1000);
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (now - t < 86400) return hm;
  const y = new Date(n); y.setDate(n.getDate() - 1);
  return `${d.toDateString() === y.toDateString() ? "Yesterday" : d.toLocaleDateString([], { weekday: "short" })} ${hm}`;
}

/** How sure Sextant is of the room, as a word and a crosshairs icon (not bars, which read as signal strength):
 *  Confident from 70%, Likely from 40%, else Unsure. */
export function confidenceLevel(conf) {
  if (conf == null || !Number.isFinite(conf)) return null;
  return conf >= 0.7 ? { word: "Confident", icon: "mdi:crosshairs-gps", colour: "var(--green-color, #4caf50)" }
    : conf >= 0.4 ? { word: "Likely", icon: "mdi:crosshairs", colour: "var(--amber-color, #ffc107)" }
      : { word: "Unsure", icon: "mdi:crosshairs-question", colour: "var(--red-color, #f44336)" };
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
