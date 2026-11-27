"""Where each thing usually is, by day type and hour.

A phone that sits on a bedside table at 07:00 on a weekday and in the kitchen
at 07:30 has a routine. Counting the seconds each thing spends in each room,
per weekday/weekend and hour of day, gives a prior for the one decision that
is a coin toss: a thing on the line between two rooms. ``prior_shift`` turns it
into a small change to the margin a challenger room must beat (see
``_elect_zone``). It never picks a room: clear evidence ignores it.

Only confident elections count (the caller's say), and every slot forgets
with a half-life of ``HALF_LIFE_S`` so a changed routine takes over in weeks.
The table is the house's own routine, so it stays in config/.storage and is
shown nowhere else; ``habit_margin_gain`` = 0 turns its use off.
"""
from __future__ import annotations

import math
import re
from datetime import datetime

HALF_LIFE_S = 21 * 86400.0
MAX_STEP_S = 60.0          # one update counts at most a minute: a gap is not time spent
MIN_SLOT_S = 20 * 60.0     # less than this in a slot says nothing yet
MAX_ZONES_PER_SLOT = 12    # a slot keeps its busiest rooms; the rest are noise
MAX_THINGS = 200
MAX_SLOTS = 48             # weekday/weekend x 24 hours


def new_store() -> dict:
    return {}


def slot_of(now: float, tz=None) -> str:
    """'wd14' / 'we14': weekday or weekend, and the local hour."""
    when = datetime.fromtimestamp(now, tz)
    return f"{'we' if when.weekday() >= 5 else 'wd'}{when.hour}"


def clean(raw) -> dict:
    """A stored table made safe to use: anything malformed is dropped."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for ent, slots in list(raw.items())[:MAX_THINGS]:
        if not isinstance(ent, str) or not isinstance(slots, dict):
            continue
        for slot, row in slots.items():
            zones = row.get("z") if isinstance(row, dict) else None
            at = row.get("at") if isinstance(row, dict) else None
            if (not isinstance(slot, str) or not re.fullmatch(r"(wd|we)([0-9]|1[0-9]|2[0-3])", slot) or not isinstance(zones, dict) or isinstance(at, bool)
                    or not isinstance(at, (int, float)) or not math.isfinite(at) or len(out.get(ent, {})) >= MAX_SLOTS):
                continue
            good = {z: float(s) for z, s in list(zones.items())[:4 * MAX_ZONES_PER_SLOT]
                    if isinstance(z, str) and isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s) and s > 0}
            good = dict(sorted(good.items(), key=lambda kv: -kv[1])[:MAX_ZONES_PER_SLOT])
            if good:
                out.setdefault(ent, {})[slot] = {"at": float(at), "z": good}
    return out


def learn(store: dict, ent: str, zone: str, now: float, last: float | None, tz=None) -> None:
    """Add the time since ``last`` (at most MAX_STEP_S) to ``zone`` in this slot."""
    if not zone or zone == "unknown" or last is None or now <= last:
        return
    row = store.setdefault(ent, {}).setdefault(slot_of(now, tz), {"at": now, "z": {}})
    zones = row["z"]
    keep = 0.5 ** (max(0.0, now - row["at"]) / HALF_LIFE_S)
    if keep < 1.0:
        for z in zones:
            zones[z] *= keep
    row["at"] = now
    zones[zone] = zones.get(zone, 0.0) + min(now - last, MAX_STEP_S)
    if len(zones) > MAX_ZONES_PER_SLOT:
        for z in sorted(zones, key=zones.get)[:len(zones) - MAX_ZONES_PER_SLOT]:
            del zones[z]
    if len(store) > MAX_THINGS:
        store.pop(next(iter(store)), None)


def share(store: dict, ent: str, zone: str, now: float, tz=None) -> float | None:
    """The fraction of this slot's time the thing spent in ``zone``, or None
    while the slot has too little history to say anything."""
    row = (store.get(ent) or {}).get(slot_of(now, tz))
    if not row:
        return None
    total = sum(row["z"].values())
    # History that has not been added to for a long time has faded: the slot only decays when it is learned into.
    faded = total * 0.5 ** (max(0.0, now - row["at"]) / HALF_LIFE_S)
    return None if faded < MIN_SLOT_S else row["z"].get(zone, 0.0) / total


def gain_for(layout, ent: str, default: float, pet_classes=frozenset({"cat", "dog", "paw"}),
             table_key: str = "class_habit_gain", top: float = 0.3, pets_off: bool = True) -> float:
    """The habit gain for a thing: its class's own setting (layout ``table_key``,
    ``class_habit_gain`` for rooms), else ``default`` - except, for rooms, a pet's
    tag, which wanders between rooms and gets 0 until the class is given a value."""
    layout = layout if isinstance(layout, dict) else {}
    cls = (layout.get("thing_classes") or {}).get(ent) if isinstance(layout.get("thing_classes"), dict) else None
    cls = cls if isinstance(cls, str) else None
    table = layout.get(table_key)
    own = table.get(cls) if isinstance(table, dict) and cls else None
    if isinstance(own, (int, float)) and not isinstance(own, bool) and math.isfinite(own) and 0.0 <= own <= top:
        return float(own)
    return 0.0 if pets_off and cls in pet_classes else default


MAX_PAUSES = 20


def paused(layout, ent: str, now: float) -> bool:
    """Whether a pause (layout ``habit_pauses``, set by sextant.pause_habits) covers this
    thing now: a holiday is not the routine, so for its length the habits are neither
    used nor learned. A pause naming no things and no classes covers everything."""
    layout = layout if isinstance(layout, dict) else {}
    classes = layout.get("thing_classes") if isinstance(layout.get("thing_classes"), dict) else {}
    pauses = layout.get("habit_pauses")
    for p in pauses if isinstance(pauses, list) else ():
        until = p.get("until") if isinstance(p, dict) else None
        if not isinstance(until, (int, float)) or isinstance(until, bool) or until <= now:
            continue
        things, kinds = p.get("things", []), p.get("classes", [])
        if not isinstance(things, list) or not isinstance(kinds, list):
            continue
        if (not things and not kinds) or ent in things or classes.get(ent) in kinds:
            return True
    return False


FLOOR_FLOOR_SHARE = 0.05   # a floor it is never on at this hour still counts this much: rare is not impossible


def floor_factors(store: dict, ent: str, floors, now: float, weight: float, tz=None) -> dict:
    """{floor: multiplier} for the floor election: the share of this slot's time
    the thing spent on each floor (its rooms' ``floor|room`` keys added up),
    raised to ``weight``. Empty (no change) with weight 0 or a slot with too
    little history. A dog asleep upstairs at 03:00 every night is upstairs at
    03:00 tonight unless the readings say plainly otherwise."""
    if weight <= 0:
        return {}
    row = (store.get(ent) or {}).get(slot_of(now, tz))
    if not row:
        return {}
    total = sum(row["z"].values())
    if total * 0.5 ** (max(0.0, now - row["at"]) / HALF_LIFE_S) < MIN_SLOT_S:
        return {}
    on: dict = {}
    for key, secs in row["z"].items():
        floor = key.split("|", 1)[0]
        on[floor] = on.get(floor, 0.0) + secs / total
    return {f: max(on.get(f, 0.0), FLOOR_FLOOR_SHARE) ** weight for f in floors}


def prior_shift(store: dict, ent: str, incumbent: str, challenger: str, now: float, gain: float, tz=None) -> float:
    """How much to move the margin a challenger must lead by: negative when
    the challenger is the habit, positive when the incumbent is. Within
    +-``gain``, and 0 when there is no history or gain is 0."""
    if gain <= 0:
        return 0.0
    a, b = share(store, ent, incumbent, now, tz), share(store, ent, challenger, now, tz)
    if a is None or b is None:
        return 0.0
    return gain * (a - b)
