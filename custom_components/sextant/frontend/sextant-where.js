// Pure: no Lit, so it loads in node tests.
/**
 * The "where is everyone" card's model: turns the Sextant location sensors
 * (and optional person and room occupancy entities) named in the card's
 * config into rows to draw.
 *
 * It reads only hass.states, and only the entities the config names. That is
 * what lets the card work behind Strimmer, which forwards a dashboard just the
 * entity ids written in its config.
 */

// Confidence bands, as on the Occupancy page.
export function confLevel(conf) {
  if (typeof conf !== "number") return null;
  if (conf >= 0.7) return { key: "confident", icon: "mdi:crosshairs-gps", color: "var(--green-color, #4caf50)", label: "Confident" };
  if (conf >= 0.4) return { key: "likely", icon: "mdi:crosshairs", color: "var(--amber-color, #ffc107)", label: "Likely" };
  return { key: "unsure", icon: "mdi:crosshairs-question", color: "var(--red-color, #f44336)", label: "Unsure" };
}

// "42m", "3h 5m", "2d 4h"; short drops the second unit.
export function fmtStay(seconds, short = false) {
  if (typeof seconds !== "number" || !(seconds >= 0)) return "";
  const m = Math.floor(seconds / 60);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60), d = Math.floor(h / 24);
  if (d >= 1) return short || h % 24 === 0 ? `${d}d` : `${d}d ${h % 24}h`;
  return short || m % 60 === 0 ? `${h}h` : `${h}h ${m % 60}m`;
}

const PET_CLASSES = new Set(["paw", "dog", "cat"]);
const BLANK = new Set(["unknown", "unavailable", "", null, undefined]);
const title = (s) => String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// Companion app activity states (iOS, then Android) that mean on the move.
const MOVING = {
  automotive: { label: "Driving", icon: "mdi:car-hatchback" }, in_vehicle: { label: "Driving", icon: "mdi:car-hatchback" },
  cycling: { label: "Cycling", icon: "mdi:bike" }, on_bicycle: { label: "Cycling", icon: "mdi:bike" },
  walking: { label: "Walking", icon: "mdi:walk" }, on_foot: { label: "Walking", icon: "mdi:walk" },
  running: { label: "Running", icon: "mdi:run" },
};

/** One entry of `entities:`, a string or {entity, person, name, pet, activity, place}, as an object. */
export function normEntry(e) {
  return typeof e === "string" ? { entity: e } : { ...(e || {}) };
}

/**
 * A new `entities:` entry for a location sensor, with its person (for photo and name) when
 * person.<same slug> exists, and the activity and geocoded-location sensors of the phone the
 * sensor tracks with (from the entity registry, `entities`), for "Driving near <town>" when away.
 */
export function withPerson(states, id, entities = {}) {
  const m = /^sensor\.(.+)_sextant_(?:person|pet)_location$/.exec(id || "");
  const person = m && states?.[`person.${m[1]}`] ? `person.${m[1]}` : null;
  const dev = entities[states?.[id]?.attributes?.tracker]?.device_id;
  const mine = dev ? Object.keys(entities).filter((x) => entities[x]?.device_id === dev) : [];
  // Android also has sleep activity sensors; its motion one is *_detected_activity, iOS's *_activity.
  const acts = mine.filter((x) => /^sensor\..+_activity$/.test(x) && !/sleep/.test(x));
  const activity = acts.find((x) => /_detected_activity$/.test(x)) || acts[0];
  // No Companion app sensors on the tracker's device: a Life360 tracker answers both itself.
  const tracker = states?.[id]?.attributes?.tracker;
  const l360 = "driving" in (states?.[tracker]?.attributes || {}) ? tracker : undefined;
  const place = mine.find((x) => /^sensor\..+_geocoded_location$/.test(x)) || l360;
  const entry = { entity: id, ...(person && { person }), ...((activity || l360) && { activity: activity || l360 }), ...(place && { place }) };
  return Object.keys(entry).length > 1 ? entry : id;
}

/**
 * A row per configured entity: name, picture, where, how long, how sure.
 * `now` is epoch seconds.
 */
export function whereRows(states, entries, now) {
  const rows = [];
  for (const raw of entries || []) {
    const e = normEntry(raw);
    const st = states?.[e.entity];
    if (!e.entity) continue;
    const a = st?.attributes || {};
    const person = e.person ? states?.[e.person] : undefined;
    const name = e.name || (person?.attributes?.friendly_name || "").split(" ")[0]
      || (a.friendly_name || "").replace(/ Location$/, "").split(" ")[0]
      || title(e.entity.split(".").pop().split("_")[0]);
    const pet = e.pet ?? (/_pet_location$/.test(e.entity) || PET_CLASSES.has(a.via_class));
    const room = BLANK.has(a.room) ? null : a.room;
    const floor = BLANK.has(a.floor) ? null : a.floor;
    let where, away = false, zone = null, moving = null, place = null;
    if (!st || st.state === "unavailable") where = "Unavailable";
    else if (a.kind === "zone" || a.presence === "away") {
      away = true;
      zone = a.zone && a.zone !== "not_home" ? title(a.zone) : null;
      // A Companion app activity sensor, or a Life360 tracker (its driving flag; its state is a zone, not an activity).
      const act = e.activity ? states?.[e.activity] : null;
      moving = !act || BLANK.has(act.state) ? null
        : e.activity.startsWith("device_tracker.") ? (act.attributes?.driving === true ? MOVING.automotive : null)
        : MOVING[String(act.state).toLowerCase()] || null;
      const gs = e.place ? states?.[e.place] : null;
      const g = gs && !BLANK.has(gs.state) ? gs.attributes || {} : {};  // a dead geocoder keeps its last town
      // A geocoder's town and state; a Life360 tracker's named place, else its street and state.
      place = [g.Locality ?? g.locality, g["Administrative Area"] ?? g.administrative_area ?? g.admin_area].filter((x) => x && x !== "N/A").join(", ")
        // Life360 lagging at its home place: not a place to show. Its places end in " (<circle name>)": dropped.
        || (gs?.state !== "home" && typeof g.place === "string" && ("driving" in g ? g.place.replace(/\s*\([^()]*\)$/, "") : g.place))
        || g.address || "";
      place ||= null;
      where = zone || (moving ? `${moving.label}${place ? ` near ${place}` : ""}` : place || "Away");
    } else where = room || title(st.state);
    rows.push({
      id: e.entity, name, pet, away, zone: !!zone, moving, place: zone ? null : place,
      picture: person?.attributes?.entity_picture || null,
      where, room: away ? null : room, spot: away ? null : (a.spot || null),
      floor: away ? null : floor,
      // Away has no since: time since the sensor last changed, when they left or reached the zone.
      stay: typeof a.since === "number" ? now - a.since : away && st?.last_changed ? now - Date.parse(st.last_changed) / 1000 : null,
      conf: typeof a.conf === "number" ? a.conf : null,
      level: away ? null : confLevel(a.conf),
      via: a.via_class || null, source: a.source || null,
    });
  }
  return rows;
}

/** The one most precise place for a row: its spot, room, floor, else "Home"; away keeps its away line. */
export function preciseWhere(r) {
  return r.away || r.where === "Unavailable" ? r.where : r.spot || r.room || r.floor || "Home";
}

/** Occupied rooms in order of first appearance, each with its rows and room mode. Away people are left out: away is not a room. */
export function groupRooms(rows, roomStates = []) {
  const modes = new Map(roomStates.filter(Boolean).map((s) => [s.attributes?.room, s.attributes?.mode]));
  const out = new Map();
  for (const r of rows) {
    if (r.away) continue;
    const key = r.room || r.where;
    if (!out.has(key)) out.set(key, { room: key, floor: r.floor, mode: modes.get(key) || null, rows: [] });
    out.get(key).rows.push(r);
  }
  return [...out.values()];
}

/**
 * The strip's chips: people one each; pets of one class on one floor fold
 * into a cluster ("3 cats") when there are at least `fold` of them.
 */
export function stripChips(rows, fold = 2) {
  const chips = [], groups = new Map();
  for (const r of rows) {
    if (!r.pet || !r.via || r.away) { chips.push({ kind: "one", row: r }); continue; }
    const key = `${r.via}|${r.floor || ""}`;
    if (!groups.has(key)) { const g = { kind: "many", cls: r.via, floor: r.floor, rows: [] }; groups.set(key, g); chips.push(g); }
    groups.get(key).rows.push(r);
  }
  return chips.flatMap((c) => c.kind === "many" && c.rows.length < fold ? c.rows.map((row) => ({ kind: "one", row })) : [c]);
}
