/** The Live page's list sections: which rows sit under a person's own
 * heading, which under Pets, and which under Everything else. Pure - the
 * panel adds the names, avatars and folding.
 *
 * One thing is enough for a person's section: the heading carries their
 * picture and where their own location sensor puts them, neither of which
 * the row can say. The exception is a pet, a person everything of whose is
 * a cat or dog tag: their tag is already a plain row under Pets, and a
 * "Spirit" heading over a row reading "Spirit" says nothing twice.
 *
 * A section once also needed two things, or one named unlike its owner -
 * which put a person back from a single phone, named after them as phones
 * are, under Everything else with no attribution at all. The pets rule
 * alone carries that carve-out now.
 */
export const PET_CLASSES = ["cat", "dog", "paw"];

/** rows: row objects with an ``ent``; owners: ent -> person entity id;
 * classes: ent -> thing class. Returns {groups: [{person, list}], pets,
 * rest}, each list in the order the rows came in. */
export function personGroups(rows, owners, classes) {
  const isPet = (p) => PET_CLASSES.includes((classes || {})[p.ent]);
  const byOwner = new Map();
  for (const p of rows) {
    const owner = (owners || {})[p.ent];
    // Only a person has a heading to sit under (the backend's owners() reads
    // the map the same way); anything else owns nothing, however it got in.
    if (typeof owner === "string" && owner.startsWith("person.")) {
      byOwner.set(owner, [...(byOwner.get(owner) || []), p]);
    }
  }
  const groups = [...byOwner]
    .map(([person, list]) => ({ person, list }))
    .filter((g) => !g.list.every((p) => isPet(p)));
  const grouped = new Set(groups.flatMap((g) => g.list.map((p) => p.ent)));
  return {
    groups,
    pets: rows.filter((p) => !grouped.has(p.ent) && isPet(p)),
    rest: rows.filter((p) => !grouped.has(p.ent) && !isPet(p)),
  };
}

/** A pet's battery badge: the battery icon nearest its level and a tone -
 * ok over 50%, mid over 30, low over 15, crit below; none without a reading. */
export function petBattery(level) {
  if (level === null || level === undefined || !Number.isFinite(level)) return { icon: "mdi:battery-unknown", tone: "none" };
  const tens = Math.round(level / 10) * 10;
  const icon = tens >= 100 ? "mdi:battery" : tens <= 0 ? "mdi:battery-outline" : `mdi:battery-${tens}`;
  return { icon, tone: level > 50 ? "ok" : level > 30 ? "mid" : level > 15 ? "low" : "crit" };
}
