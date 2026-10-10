"""Is a layout safe to store? The one check every way in uses.

The positioning cycle reads the layout every few seconds and trusts its
shape: floors are dicts with a name, the lists on them hold dicts, and every
coordinate is a finite number. A layout that breaks that (a hand-edited
upload, a script, ``NaN`` - which Python's JSON parser accepts) used to be
stored as it was and then fail every cycle until someone noticed. This is
asked first, by ``layout/save``, the floor upload and snapshot restore.

Deliberately structural: it says nothing about whether a room makes sense,
only that the cycle can read it. Pure: no Home Assistant imports.
"""
from __future__ import annotations

import math

# The lists a floor may carry, each of dicts.
FLOOR_LISTS = ("receivers", "zones", "subzones", "pins", "remarks", "radars", "access_points")
# Top-level maps keyed by thing (or by anything): each must be a dict when present.
MAP_PREFIXES = ("thing_",)
# Upper bounds that keep a single save from stalling the loop (see the shapes
# and the spot confinement, which walk every vertex).
MAX_FLOORS = 50
MAX_ITEMS_PER_LIST = 2000
MAX_VERTICES = 2000


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _point_problem(p, where) -> str | None:
    if not isinstance(p, dict):
        return f"{where}: a point must be an object with x and y"
    for k in ("x", "y", "r"):
        if k in p and p[k] is not None and not _finite(p[k]):
            return f"{where}: {k} must be a finite number"
    return None


def _cords_problem(cords, where) -> str | None:
    """``cords`` is a point or circle ({x, y[, r]}) or a list of points."""
    if cords is None:
        return None
    if isinstance(cords, dict):
        return _point_problem(cords, where)
    if isinstance(cords, list):
        if len(cords) > MAX_VERTICES:
            return f"{where}: more than {MAX_VERTICES} corners"
        for i, p in enumerate(cords):
            if (problem := _point_problem(p, f"{where} corner {i + 1}")) is not None:
                return problem
        return None
    return f"{where}: cords must be a point or a list of points"


def layout_problem(layout) -> str | None:
    """Why this layout cannot be stored, or None when it can."""
    if not isinstance(layout, dict):
        return "the layout must be an object"
    floors = layout.get("floor")
    if not isinstance(floors, list):
        return "layout.floor must be a list"
    if len(floors) > MAX_FLOORS:
        return f"more than {MAX_FLOORS} floors"
    for n, floor in enumerate(floors):
        if not isinstance(floor, dict) or not isinstance(floor.get("name"), str) or not floor["name"]:
            return f"floor {n + 1}: every floor needs a name"
        name = floor["name"]
        scale = floor.get("scale")
        if scale is not None and not (_finite(scale) and scale > 0):
            return f"{name}: scale must be a positive number"
        for key in ("level", "elevation", "bias"):
            if floor.get(key) is not None and not _finite(floor[key]):
                return f"{name}: {key} must be a number"
        for key in FLOOR_LISTS:
            items = floor.get(key)
            if items is None:
                continue
            if not isinstance(items, list):
                return f"{name}: {key} must be a list"
            if len(items) > MAX_ITEMS_PER_LIST:
                return f"{name}: more than {MAX_ITEMS_PER_LIST} {key}"
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    return f"{name}: {key} {i + 1} must be an object"
                label = item.get("entity_id") or item.get("name") or item.get("mac") or f"{key} {i + 1}"
                if (problem := _cords_problem(item.get("cords"), f"{name}: {label}")) is not None:
                    return problem
    for key, value in layout.items():
        if any(key.startswith(p) for p in MAP_PREFIXES) and value is not None and not isinstance(value, dict):
            return f"layout.{key} must be an object"
    if layout.get("tuning") is not None and not isinstance(layout["tuning"], dict):
        return "layout.tuning must be an object"
    return None
