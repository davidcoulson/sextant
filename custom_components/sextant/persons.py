"""Where a person is, from the things they own.

A thing can name its owner, a Home Assistant person (thing_owners in the
layout). A person's location is then one of their things' locations, and the
question is which one speaks for them. The phone left on the couch for an
hour does not; the watch that just crossed the room does. So:

1. Only things heard recently (within stale_after_secs) and placed in a room.
2. A thing that arrived where it is within RECENT_MOVE_SECS beats one that
   has sat there longer - it is being carried. Arrival is metres moved
   (settled_since), not the tracker's own "moving" flag: a watch on its
   nightstand whose fix alternates between two points reads as moving. Among those,
   what is usually on a body wins: a pet's own tag, a watch, a phone.
3. When nothing is on the move, the thing that arrived where it is most
   recently wins: the phone that came downstairs this morning, not the
   watch that has sat on its charger since last night. Class does not
   decide here - it did at first, and the watch on the nightstand won.

Only things that give their owner's location take part (locates_owner): by
class a watch, a phone or a person's or pet's own tag; headphones, keys, a
bag only when the thing is switched on for it.
4. Then whichever moved most recently.

Pure: the caller hands in each thing's latest published row.
"""

from __future__ import annotations

import math

# A thing still for longer than this is probably not being carried.
RECENT_MOVE_SECS = 600.0
# "Where it is" for arrival purposes: within this many metres of its place.
# Measured in metres, not by room or spot name - a watch on a nightstand at
# the edge of its spot flips between the spot and the room with every
# wobble, and every flip looked like a fresh arrival.
STAY_RADIUS_M = 2.0
# Somewhere else for less than this is noise, not a move: a stray fix, or the
# minute after a restart when a watch on its nightstand was placed a floor
# down three times running.
MOVE_CONFIRM_SECS = 120.0
# Higher speaks for its owner first, among things equally recently moved.
CARRY_PRIORITY = {"cat": 4, "dog": 4, "paw": 4, "watch": 3, "phone": 2, "headphones": 1}
# Classes whose place is their owner's place, unless the thing says otherwise
# (thing_locates_owner). Headphones, keys, a bag go with you some of the time;
# where they are is not where you are.
LOCATES_BY_DEFAULT = {"watch", "phone", "person", "man", "woman", "child", "cat", "dog", "paw"}
# The sensors each person gets: (suffix, label).
PERSON_SENSOR_KINDS = [
    ("sextant_person_location", "Sextant Location"),
    ("sextant_person_room", "Sextant Room"),
    ("sextant_person_floor", "Sextant Floor"),
]


def owners(layout) -> dict[str, list[str]]:
    """person entity id -> the things it owns."""
    out: dict[str, list[str]] = {}
    raw = layout.get("thing_owners") if isinstance(layout, dict) else None
    for thing, person in (raw or {}).items():
        if isinstance(person, str) and person.startswith("person."):
            out.setdefault(person, []).append(thing)
    return out


def locates_owner(layout, ent, cls) -> bool:
    """Whether this thing's place may stand for its owner's: its own setting, else its class."""
    own = (layout.get("thing_locates_owner") or {}).get(ent) if isinstance(layout, dict) else None
    if isinstance(own, bool):
        return own
    return cls in LOCATES_BY_DEFAULT


# What a battery sensor says when its device is on a charger: iCloud3 reports
# Charging / Charged / Full, Apple's Find My "Charged" at 100 %, the companion
# app Charging / Full. "Not Charging" and "NotCharging" are off the charger.
CHARGER_STATES = {"charging", "charged", "full", "on"}


def on_charger(state) -> bool:
    """Whether a battery (or charging binary) sensor's state says it is on a charger.

    Anything unreadable - unavailable, unknown, no sensor - is False: a sensor
    that has nothing to say must not take a thing out of the running.
    """
    return isinstance(state, str) and state.strip().lower() in CHARGER_STATES


def settled_since(points, here, radius=STAY_RADIUS_M, confirm_secs=MOVE_CONFIRM_SECS):
    """When a thing arrived within ``radius`` metres of ``here``, from its history.

    ``points``: (t, floor, x_m, y_m), oldest first; ``here``: (floor, x_m, y_m).
    Walks back from the newest point until the thing had been elsewhere
    (another floor, or farther than ``radius``) for ``confirm_secs``; returns
    the time of the first point of the stay that followed, or None with no
    history here. Shorter absences are passed over as noise.
    """
    floor, hx, hy = here
    since = None
    for t, f, x, y in reversed(points):
        if f == floor and x is not None and y is not None and math.hypot(x - hx, y - hy) <= radius:
            since = t
        elif since is not None and since - t >= confirm_secs:
            break
    return since


def pick(things, now: float, stale_after: float):
    """The thing that speaks for its owner now, or None.

    ``things`` are dicts: ent, cls, updated (epoch s),
    arrived (epoch s: when it came within STAY_RADIUS_M of where it is now),
    zone, sub_zone, floor.
    """
    fresh = [
        t for t in things
        if isinstance(t.get("updated"), (int, float)) and now - t["updated"] <= stale_after
        and t.get("zone") not in (None, "", "unknown")
        and not t.get("on_charger")   # a watch on its charger is not on anybody's wrist
    ]
    if not fresh:
        return None

    def key(t):
        arrived = t.get("arrived")
        age = max(0.0, now - arrived) if isinstance(arrived, (int, float)) else float("inf")
        recent = age <= RECENT_MOVE_SECS
        return (not recent, -CARRY_PRIORITY.get(t.get("cls"), 0) if recent else 0, age)

    return min(fresh, key=key)


def considered(things, now):
    """What the choice was between, for the location sensor: each thing that
    gives its owner's location, where it is and for how many minutes it has
    stayed there. Shows why the person reads where they do."""
    return [
        {"thing": t["ent"], "where": t.get("sub_zone") if t.get("sub_zone") not in (None, "", "unknown") else t.get("zone"),
         "here_for_min": round((now - t["arrived"]) / 60) if isinstance(t.get("arrived"), (int, float)) else None,
         **({"on_charger": True} if t.get("on_charger") else {})}
        for t in things
    ]


def states(best, why=None):
    """(suffix -> (state, attributes)) for a person's sensors from the chosen thing."""
    if best is None:
        blank = {"room": "unknown", "spot": None, "floor": "unknown", "area_id": None, "floor_id": None, "via": None}
        return {
            "sextant_person_location": ("unknown", {"kind": "room", **blank}),
            "sextant_person_room": ("unknown", {"area_id": None, "via": None}),
            "sextant_person_floor": ("unknown", {"via": None}),
        }
    spot = best.get("sub_zone")
    spot = spot if spot not in (None, "", "unknown") else None
    room, floor = best.get("zone"), best.get("floor") or "unknown"
    area_id, floor_id = best.get("area") or (None, None)
    via = {"via": best["ent"]}
    return {
        "sextant_person_location": (spot or room, {"kind": "spot" if spot else "room", "room": room, "spot": spot,
                                                   "floor": floor, "area_id": area_id, "floor_id": floor_id,
                                                   **via, "considered": why or []}),
        "sextant_person_room": (room, {"area_id": area_id, **via}),
        "sextant_person_floor": (floor, via),
    }
