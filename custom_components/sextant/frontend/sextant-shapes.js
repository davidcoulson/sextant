/**
 * What a save would destroy, with no DOM: imported by the editor, and
 * directly by the tests. The server runs the same check (snapshots.degraded)
 * and reports back, but by then the save is done; this one runs before the
 * draft is sent, so the editor can ask first.
 */

const KINDS = [["room", "zones", "zone_id"], ["spot", "subzones", "sub_zone_id"]];

function shapes(layout) {
  const out = new Map();
  for (const f of layout?.floor || []) {
    for (const [kind, key, idKey] of KINDS) {
      for (const item of f?.[key] || []) {
        if (!item) continue;
        out.set(`${f.name}\u0000${kind}\u0000${item.entity_id ?? item[idKey]}`, (item.cords || []).length);
      }
    }
  }
  return out;
}

/** Every room or spot that `after` leaves with fewer than three corners
 * where `before` had three or more, in words. Three is the least that
 * encloses any area; one or two draw as nothing, and the shape silently
 * disappears from the plan. Deleting a shape outright is not reported: people
 * do that on purpose. */
export function lostShapes(before, after) {
  const was = shapes(before), now = shapes(after), lost = [];
  for (const [key, corners] of was) {
    const left = now.get(key);
    if (corners >= 3 && left !== undefined && left < 3) {
      const [floor, kind, name] = key.split("\u0000");
      lost.push(`${kind} "${name}" on ${floor} drops from ${corners} corners to ${left} and would no longer be drawn`);
    }
  }
  return lost;
}

/** The part of a layout the editor owns, as a string to compare: the floors,
 * without what the server writes into them (ws.merge_editor_layout keeps
 * those through a save: calibration, bias_field, each proxy's correction)
 * and without the editor's display-only marks. Two layouts with the same key
 * differ in nothing a save from the editor would overwrite. */
export function planKey(layout) {
  const floors = JSON.parse(JSON.stringify(layout?.floor || []));
  for (const f of floors) {
    delete f.calibration; delete f.bias_field;
    for (const r of f.receivers || []) {
      // A proxy held out of calibration keeps the editor's correction through a save.
      if (r.calibrate !== false) delete r.correction;
      delete r.unmatched; delete r.label;
    }
    for (const q of f.pins || []) { delete q.linked; delete q.miss; delete q.missLabel; }
  }
  return JSON.stringify(floors);
}

const nameKey = (s) => String(s ?? "").trim().toLowerCase();

/** "Room 3": the first "<base> N" no shape in the list is named yet (deleting Room 1 must not make the next one a second Room 2). */
export function freeName(base, list) {
  const taken = new Set((list || []).map((s) => nameKey(s.entity_id)));
  let n = 1;
  while (taken.has(nameKey(`${base} ${n}`))) n += 1;
  return `${base} ${n}`;
}

/** Another room (or no-go area, or spot) in the list has this one's name: rooms are told apart by name. */
export function sameName(list, item) {
  const k = nameKey(item?.entity_id);
  return !!k && (list || []).some((s) => s !== item && !!s.no_go === !!item.no_go && nameKey(s.entity_id) === k);
}
