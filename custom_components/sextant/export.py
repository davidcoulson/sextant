"""The floor plan and who is where, as data: ``sextant.get_map``.

The plan is drawn for the map, and the sensors say where each thing and
person is one at a time. An automation, a script or an AI assistant asking
"what is the house like, and where is everyone" wants the two together, in
metres rather than plan pixels, and in one answer: every floor's rooms with
their outlines, areas and neighbours, the spots and proxies in each, and the
people, pets and things in them right now.

Pure: the service handler in ``__init__`` gathers the layout, this cycle's
rows, the person sensors' states and the display names, and ``build_map``
turns them into the response. Nothing here touches Home Assistant.
"""
import time
from datetime import datetime, timezone
from itertools import combinations

import numpy as np
from shapely.geometry import Point, Polygon

from . import persons as persons_mod
from .kpi import NEIGHBOUR_REACH_M

# Plan coordinates are rounded to this many decimals of a metre: a centimetre
# is finer than a hand-drawn plan, and keeps the response readable.
_DECIMALS = 2

FRAME = ("Each floor's coordinates are plan coordinates: metres from the top-left corner of that "
         "floor's plan, x to the right and y down. Floors are not aligned to one another.")


def _iso(stamp):
    if not isinstance(stamp, (int, float)):
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")


def _ring(shape):
    """A shape's corners as (x, y) px, or None for fewer than three.

    A polygon keeps its drawn order. A legacy rectangle (no ``poly`` flag,
    four corners stored in scan order) is ordered around its centre, the way
    the positioning code reads it, so it does not come out as a bow tie.
    """
    pts = [(float(p["x"]), float(p["y"])) for p in shape.get("cords") or []
           if isinstance(p, dict) and isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float))]
    if len(pts) < 3:
        return None
    if not shape.get("poly") and len(pts) == 4:
        cx = sum(p[0] for p in pts) / 4
        cy = sum(p[1] for p in pts) / 4
        pts.sort(key=lambda p: np.arctan2(p[1] - cy, p[0] - cx))
    return pts


def _poly(pts):
    poly = Polygon(pts).buffer(0)
    return None if poly.is_empty else poly


def _scaled(value, scale):
    return None if scale is None else round(value / scale, _DECIMALS)


def _outline(pts, scale):
    return [[_scaled(x, scale), _scaled(y, scale)] for x, y in pts]


def _point(cords, scale):
    """A placed item's position as (x_m, y_m), or (None, None) without one."""
    if not isinstance(cords, dict):
        return None, None
    x, y = cords.get("x"), cords.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None, None
    return _scaled(x, scale), _scaled(y, scale)


def _room_of(x, y, rooms):
    """The name of the room a plan point is in, or None."""
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    p = Point(x, y)
    for name, poly in rooms:
        if poly.contains(p):
            return name
    return None


def people_from_states(get_state, layout):
    """What the person sensors say, one entry per person Sextant places.

    ``get_state(entity_id)`` is ``hass.states.get``. A pet is a person entity
    whose every thing is a pet tag (persons.pet_persons); its sensors are the
    ``_sextant_pet_`` ones.
    """
    classes = layout.get("thing_classes") or {}
    by_person = persons_mod.owners(layout)
    pets = persons_mod.pet_persons(by_person, classes)
    out = []
    for person in by_person:
        is_pet = person in pets
        slug = person.split(".", 1)[1]
        st = get_state(persons_mod.sensor_entity_id(slug, "sextant_person_location", is_pet))
        if st is None:
            continue
        attrs = getattr(st, "attributes", None) or {}
        entity = get_state(person)
        name = (getattr(entity, "attributes", None) or {}).get("friendly_name") or slug
        out.append({
            "person": person,
            "name": name,
            "kind": "pet" if is_pet else "person",
            "location": st.state,
            "floor": attrs.get("floor"),
            "room": attrs.get("room"),
            "spot": attrs.get("spot"),
            "presence": attrs.get("presence"),
            "via": attrs.get("via"),
            "source": attrs.get("source"),
            "last_heard": attrs.get("last_heard"),
        })
    return out


def build_map(layout, rows=(), people=(), names=None, now=None, floor=None, presence_of=None):
    """The response of ``sextant.get_map``.

    ``rows`` are this cycle's position rows (``apitricords``), ``people`` is
    ``people_from_states``'s list, ``names`` maps a thing key to its display
    name, ``presence_of(ent)`` gives here / quiet / away. ``floor`` limits
    the answer to one floor by name; a name that is not a floor raises
    ValueError.
    """
    now = time.time() if now is None else now
    names = names or {}
    classes = layout.get("thing_classes") or {}
    owners = layout.get("thing_owners") or {}
    floors = [f for f in (layout.get("floor") or []) if isinstance(f, dict) and f.get("name")]
    if floor is not None:
        floors = [f for f in floors if f.get("name") == floor]
        if not floors:
            raise ValueError(f"no floor called {floor!r}")
    wanted = {f["name"] for f in floors}
    rows = [r for r in rows if isinstance(r, dict) and r.get("ent")]
    people = [p for p in people if isinstance(p, dict)]

    things = []
    for r in rows:
        if r.get("floor") not in wanted:
            continue
        scale = next((f.get("scale") for f in floors if f["name"] == r["floor"]), None)
        scale = scale if isinstance(scale, (int, float)) and scale > 0 else None
        cords = r.get("cords") if isinstance(r.get("cords"), (list, tuple)) and len(r.get("cords")) == 2 else (None, None)
        ent = r["ent"]
        things.append({
            "key": ent,
            "name": names.get(ent) or ent,
            "class": classes.get(ent),
            "owner": owners.get(ent),
            "floor": r.get("floor"),
            "room": "Outside" if r.get("outside") else r.get("zone"),
            "spot": r.get("sub_zone") if r.get("sub_zone") not in ("", "unknown") else None,
            "x_m": _scaled(cords[0], scale) if isinstance(cords[0], (int, float)) else None,
            "y_m": _scaled(cords[1], scale) if isinstance(cords[1], (int, float)) else None,
            "confidence": r.get("conf"),
            "presence": presence_of(ent) if presence_of else None,
            "in_room_since": _iso(r.get("since")),
            "last_heard": _iso(r.get("updated")),
        })

    out_floors = []
    for f in floors:
        scale = f.get("scale")
        scale = scale if isinstance(scale, (int, float)) and scale > 0 else None
        zones = [z for z in f.get("zones") or [] if isinstance(z, dict) and z.get("entity_id")]
        rooms, no_go = [], []
        polys = []        # (name, polygon px) of the rooms, for what is in which
        for z in zones:
            pts = _ring(z)
            if pts is None:
                continue
            poly = _poly(pts)
            if poly is None:
                continue
            entry = {"name": z["entity_id"]}
            if scale is None:
                entry["outline_px"] = [[round(x, 1), round(y, 1)] for x, y in pts]
            else:
                entry["outline_m"] = _outline(pts, scale)
            if z.get("no_go"):
                no_go.append(entry)
                continue
            polys.append((z["entity_id"], poly))
            c = poly.representative_point()
            entry.update({
                "area_id": z.get("area_id") if isinstance(z.get("area_id"), str) and z.get("area_id") else None,
                "area_m2": None if scale is None else round(poly.area / (scale * scale), 1),
                "centre_m": [_scaled(c.x, scale), _scaled(c.y, scale)],
                "neighbours": [],
                "spots": [],
                "proxies": [],
                "occupants": [],
                "things": [],
            })
            entry["_poly"] = poly
            entry["_id"] = z.get("zone_id")
            rooms.append(entry)
        by_name = {r["name"]: r for r in rooms}
        by_id = {r["_id"]: r for r in rooms if r["_id"]}
        # Neighbours: rooms whose outlines come within reach of each other,
        # the same rule the stability KPI uses to tell a walk from a jump.
        reach_px = NEIGHBOUR_REACH_M * scale if scale else 0.0
        for a, b in combinations(rooms, 2):
            if a["_poly"].distance(b["_poly"]) <= reach_px:
                a["neighbours"].append(b["name"])
                b["neighbours"].append(a["name"])
        for s in f.get("subzones") or []:
            if not isinstance(s, dict) or not s.get("entity_id"):
                continue
            pts = _ring(s)
            if pts is None:
                continue
            poly = _poly(pts)
            if poly is None:
                continue
            c = poly.representative_point()
            # Its room: the parent it was drawn in, else the room under its
            # first corner, else the room under its middle.
            room = by_id.get(s.get("parent"))
            if room is None:
                room = by_name.get(_room_of(pts[0][0], pts[0][1], polys) or _room_of(c.x, c.y, polys))
            if room is None:
                continue
            spot = {"name": s["entity_id"], "centre_m": [_scaled(c.x, scale), _scaled(c.y, scale)]}
            if scale is None:
                spot["outline_px"] = [[round(x, 1), round(y, 1)] for x, y in pts]
            else:
                spot["outline_m"] = _outline(pts, scale)
                spot["area_m2"] = round(poly.area / (scale * scale), 2)
            room["spots"].append(spot)
        proxies = []
        for r in f.get("receivers") or []:
            if not isinstance(r, dict) or not r.get("entity_id"):
                continue
            cords = r.get("cords") if isinstance(r.get("cords"), dict) else {}
            x_m, y_m = _point(cords, scale)
            room = _room_of(cords.get("x"), cords.get("y"), polys)
            proxies.append({
                "name": r["entity_id"],
                "x_m": x_m, "y_m": y_m,
                "height_m": r.get("height") if isinstance(r.get("height"), (int, float)) else None,
                "room": room,
                "in_use": r.get("solve") is not False,
            })
            if room in by_name:
                by_name[room]["proxies"].append(r["entity_id"])
        access_points = []
        for a in f.get("access_points") or []:
            if not isinstance(a, dict):
                continue
            x_m, y_m = _point(a.get("cords"), scale)
            access_points.append({"name": a.get("name") or a.get("mac"), "mac": a.get("mac"), "x_m": x_m, "y_m": y_m,
                                  "room": _room_of((a.get("cords") or {}).get("x"), (a.get("cords") or {}).get("y"), polys)})
        mmwave = []
        for r in f.get("radars") or []:
            if not isinstance(r, dict):
                continue
            x_m, y_m = _point(r.get("cords"), scale)
            mmwave.append({"device_id": r.get("device_id"), "x_m": x_m, "y_m": y_m, "heading": r.get("heading"),
                           "room": _room_of((r.get("cords") or {}).get("x"), (r.get("cords") or {}).get("y"), polys)})
        for p in people:
            if p.get("floor") == f["name"] and p.get("room") in by_name and p.get("presence") not in (None, "away"):
                by_name[p["room"]]["occupants"].append({"name": p.get("name"), "kind": p.get("kind"), "spot": p.get("spot")})
        for t in things:
            if t["floor"] == f["name"] and t["room"] in by_name and t["presence"] != "away":
                by_name[t["room"]]["things"].append({"name": t["name"], "key": t["key"], "class": t["class"], "spot": t["spot"]})
        for r in rooms:
            r.pop("_poly", None)
            r.pop("_id", None)
        out_floors.append({
            "name": f["name"],
            "floor_id": f.get("floor_id") if isinstance(f.get("floor_id"), str) else None,
            "level": f.get("level") if isinstance(f.get("level"), int) else None,
            "elevation_m": f.get("elevation") if isinstance(f.get("elevation"), (int, float)) else None,
            "scaled": scale is not None,
            "rooms": rooms,
            "no_go": no_go,
            "proxies": proxies,
            "access_points": access_points,
            "mmwave": mmwave,
        })

    return {
        "generated_at": _iso(now),
        "units": {"length": "m", "area": "m2"},
        "frame": FRAME,
        "floors": out_floors,
        "people": [p for p in people if floor is None or p.get("floor") == floor],
        "things": things,
    }

