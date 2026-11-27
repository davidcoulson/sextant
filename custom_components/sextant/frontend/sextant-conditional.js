// Pure: no Lit, so it loads in node tests.
/**
 * The Sextant conditional card's model: whose place it tests (a named person,
 * or the person linked to whoever is viewing the dashboard), where that person
 * is, and whether the card shows.
 */

const BLANK = new Set(["unknown", "unavailable", "", null, undefined]);
const fold = (s) => String(s).trim().toLowerCase();
const list = (v) => (Array.isArray(v) ? v : BLANK.has(v) ? [] : [v]).filter((x) => !BLANK.has(x));

/** The person.* entity linked to a Home Assistant user, or null. */
export function personForUser(states, userId) {
  if (!userId) return null;
  return Object.keys(states || {}).find((id) => id.startsWith("person.") && states[id]?.attributes?.user_id === userId) || null;
}

/** Where a person (or pet) is, from their Sextant location sensor: {room, floor}; nulls when away, unknown or missing. */
export function placeOf(states, person) {
  const none = { room: null, floor: null };
  if (!person) return none;
  const slug = person.split(".").pop();
  const s = states?.[`sensor.${slug}_sextant_person_location`] || states?.[`sensor.${slug}_sextant_pet_location`];
  const a = s?.attributes || {};
  if (!s || s.state === "unavailable" || a.presence === "away" || a.kind === "zone") return none;
  return { room: BLANK.has(a.room) ? null : a.room, floor: BLANK.has(a.floor) ? null : a.floor };
}

/** Whether the card shows: the viewer is one of `users` (when set), and the person is in one of `rooms` or on one of `floors` (when either is set). */
export function shows(config, { userId, room, floor }) {
  const users = list(config.users);
  if (users.length && !users.includes(userId)) return false;
  const rooms = list(config.rooms).map(fold), floors = list(config.floors).map(fold);
  if (!rooms.length && !floors.length) return true;
  return (room != null && rooms.includes(fold(room))) || (floor != null && floors.includes(fold(floor)));
}

/** Whether the config tests a place at all (so the card needs to know whose). */
export const testsPlace = (config) => list(config.rooms).length > 0 || list(config.floors).length > 0;

/** The editor's choices: rooms and floors from the room occupancy sensors, and the people linked to users. */
export function choices(states) {
  const rooms = new Set(), floors = new Set(), users = [];
  for (const [id, s] of Object.entries(states || {})) {
    const a = s?.attributes || {};
    if (id.startsWith("binary_sensor.") && id.endsWith("_sextant_occupancy")) {
      if (!BLANK.has(a.room)) rooms.add(a.room);
      if (!BLANK.has(a.floor)) floors.add(a.floor);
    } else if (id.startsWith("person.") && a.user_id) users.push({ value: a.user_id, label: a.friendly_name || id });
  }
  const opts = (set) => [...set].sort((x, y) => x.localeCompare(y)).map((v) => ({ value: v, label: v }));
  return { rooms: opts(rooms), floors: opts(floors), users: users.sort((x, y) => x.label.localeCompare(y.label)) };
}
