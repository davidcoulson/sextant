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

/** One entry of `entities:`, a string or {entity, person, name, pet}, as an object. */
export function normEntry(e) {
  return typeof e === "string" ? { entity: e } : { ...(e || {}) };
}

/** A new `entities:` entry for a location sensor, with its person (for photo and name) when person.<same slug> exists. */
export function withPerson(states, id) {
  const m = /^sensor\.(.+)_sextant_(?:person|pet)_location$/.exec(id || "");
  const person = m && `person.${m[1]}`;
  return person && states?.[person] ? { entity: id, person } : id;
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
    let where, away = false;
    if (!st || st.state === "unavailable") where = "Unavailable";
    else if (a.kind === "zone" || a.presence === "away") {
      away = true;
      where = a.zone && a.zone !== "not_home" ? title(a.zone) : "Away";
    } else where = room || title(st.state);
    rows.push({
      id: e.entity, name, pet, away,
      picture: person?.attributes?.entity_picture || null,
      where, room: away ? null : room, spot: away ? null : (a.spot || null),
      floor: away ? null : floor,
      stay: typeof a.since === "number" ? now - a.since : null,
      conf: typeof a.conf === "number" ? a.conf : null,
      level: away ? null : confLevel(a.conf),
      via: a.via_class || null, source: a.source || null,
    });
  }
  return rows;
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
