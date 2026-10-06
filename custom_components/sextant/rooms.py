"""Who is in each room: the per-room occupancy sensors.

Sextant's other sensors answer "where is this thing?" and "where is this
person?". These answer the question an automation about a room asks -
"is anyone in the Kitchen, and who?" - as one binary sensor per room,
``on`` while any tracked thing is placed there, with the people, pets and
things as attributes. It is also the shape an occupancy aggregator such as
Area Occupancy Detection takes as an input: a binary that carries identity.

Pure: no Home Assistant imports, so it loads in the unit tests. The
platform (binary_sensor.py) and the cycle hook (__init__._update_room_sensors)
do the plumbing.
"""
from __future__ import annotations

import re

PET_CLASSES = frozenset({"cat", "dog", "paw"})

# Presence states that keep a thing counted in its room: heard lately, or
# not heard for a few minutes but still placed (the room sensor holds its
# value through that gap too). "away" drops it.
COUNTED = ("here", "quiet")
_RANK = {"here": 0, "quiet": 1}


def slug(text: str) -> str:
    """A lower-case entity-id-safe slug: 'Great Room' -> 'great_room'."""
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return s or "room"


def room_keys(layout) -> list[dict]:
    """Every room on every floor, with its links: [{floor, room, area_id, floor_id}].

    No-go zones are not rooms. Order is the layout's: floors as listed,
    rooms as listed, so the sensors appear the way the plan reads.
    """
    out = []
    floors = layout.get("floor") if isinstance(layout, dict) else None
    for floor in floors or []:
        if not isinstance(floor, dict) or not floor.get("name"):
            continue
        floor_id = floor.get("floor_id") if isinstance(floor.get("floor_id"), str) else None
        for zone in floor.get("zones") or []:
            if not isinstance(zone, dict) or zone.get("no_go") or not zone.get("entity_id"):
                continue
            area = zone.get("area_id")
            out.append({"floor": floor["name"], "room": zone["entity_id"],
                        "area_id": area if isinstance(area, str) and area else None, "floor_id": floor_id})
    return out


def ids_for(keys) -> dict[tuple[str, str], dict]:
    """(floor, room) -> {slug, unique_id, entity_id, name}.

    The entity id is the room's name alone - ``binary_sensor.kitchen_sextant_occupancy``
    - unless two floors have a room of that name, when both get the floor in
    front. The unique id always carries the floor, so a room renamed on one
    floor does not take over another's history.
    """
    by_room: dict[str, int] = {}
    for k in keys:
        by_room[slug(k["room"])] = by_room.get(slug(k["room"]), 0) + 1
    out = {}
    for k in keys:
        room_slug = slug(k["room"])
        shown = f"{slug(k['floor'])}_{room_slug}" if by_room[room_slug] > 1 else room_slug
        out[(k["floor"], k["room"])] = {
            "slug": shown,
            "unique_id": f"sextant_room_occupancy_{slug(k['floor'])}_{room_slug}",
            "entity_id": f"binary_sensor.{shown}_sextant_occupancy",
            "name": f"{k['room']} Sextant Occupancy" if by_room[room_slug] == 1 else f"{k['room']} ({k['floor']}) Sextant Occupancy",
        }
    return out


def occupancy(keys, rows, presence_of, classes=None, names=None, person_rooms=None, stands_for_someone=None) -> dict[tuple[str, str], tuple[bool, dict]]:
    """The state and attributes of every room's sensor.

    ``rows`` are the cycle's position rows ({ent, zone, floor, sub_zone, ...});
    ``presence_of(ent)`` gives here / quiet / away; ``classes`` and ``names``
    are the layout's thing classes and display names; ``person_rooms`` is
    {person display name: (floor, room)} for each person Sextant currently
    places (from the person sensors), so a person is listed in the room the
    thing speaking for them is in, not in every room one of their things is.

    Occupancy is about people and pets. A room is ``on`` while something
    that stands for someone is in it - a phone, a watch, a pet's tag
    (``stands_for_someone(ent)``, persons.locates_owner by default) - or a
    person is placed there. A wallet left on the counter or luggage in a
    bedroom is listed under ``things`` but does not make the room occupied,
    and a robot vacuum is not a thing here at all.
    """
    classes = classes or {}
    names = names or {}
    if stands_for_someone is None:
        def stands_for_someone(ent):
            return classes.get(ent) in PET_CLASSES or classes.get(ent) in ("phone", "watch", "person", "man", "woman", "child")
    by_key: dict[tuple[str, str], list[tuple[str, str, str | None, bool]]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("robot"):
            continue
        ent, zone, floor = row.get("ent"), row.get("zone"), row.get("floor")
        if not ent or not zone or zone == "unknown" or not floor:
            continue
        presence = presence_of(ent)
        if presence not in COUNTED:
            continue
        spot = row.get("sub_zone")
        by_key.setdefault((floor, zone), []).append((ent, presence, spot if spot and spot != "unknown" else None, bool(stands_for_someone(ent))))
    people_by_key: dict[tuple[str, str], list[str]] = {}
    for person, where in (person_rooms or {}).items():
        if where:
            people_by_key.setdefault(tuple(where), []).append(person)
    out = {}
    for k in keys:
        key = (k["floor"], k["room"])
        here = sorted(by_key.get(key, []), key=lambda t: (_RANK[t[1]], names.get(t[0], t[0]).lower()))
        counted = [t for t in here if t[3]]
        things = [names.get(ent, ent) for ent, _p, _s, _c in here]
        pets = [names.get(ent, ent) for ent, _p, _s, _c in here if classes.get(ent) in PET_CLASSES]
        people = sorted(people_by_key.get(key, []))
        presence = min((p for _e, p, _s, _c in counted), key=_RANK.get, default=None)
        out[key] = (bool(counted) or bool(people), {
            "room": k["room"], "floor": k["floor"], "area_id": k["area_id"], "floor_id": k["floor_id"],
            "count": len(counted), "people": people, "pets": pets, "things": things,
            "spots": sorted({s for _e, _p, s, _c in counted if s}),
            "presence": presence,
        })
    return out


def people_home(presences: dict[str, str], pets=()) -> tuple[int, dict]:
    """How many people Sextant hears in the house, from {person name: presence}.

    ``pets`` names the persons that are pets (Home Assistant lets a cat be a
    person): they are listed apart and not counted.
    """
    pets = set(pets)
    home = sorted(n for n, p in presences.items() if p in COUNTED and n not in pets)
    away = sorted(n for n, p in presences.items() if p not in COUNTED and n not in pets)
    pets_home = sorted(n for n, p in presences.items() if p in COUNTED and n in pets)
    return len(home), {"home": home, "away": away, "pets_home": pets_home}
