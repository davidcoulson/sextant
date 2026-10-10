"""The whole property on one map: every floor in the house frame, placed on
the street or aerial map by a site the user lines up.

registration.py already carries each floor into the *house frame* - the
reference floor's plan in metres - from the anchors shared between floors.
This module turns a layout into what the Property view draws in that frame:
each floor's rooms, its proxies and access points (outdoor ones included),
and the per-floor transform the page uses to bring live positions in. The
site - where the house frame's origin sits on the earth and which way it
turns - is the one thing the user sets (``layout["site"]``).

A floor the anchors do not register is drawn in its own metres, unrotated:
right for a house of one floor, and visibly off (so it gets anchored) for a
second one.

Pure: no Home Assistant imports.
"""
from __future__ import annotations

import math

from . import registration


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def clean_site(site) -> dict | None:
    """{"lat", "lon", "rotation"} from a stored or submitted site, else None.
    Rotation is degrees clockwise, kept in [0, 360)."""
    if not isinstance(site, dict):
        return None
    lat, lon, rot = _num(site.get("lat")), _num(site.get("lon")), _num(site.get("rotation")) or 0.0
    if lat is None or lon is None or not (-85.0 <= lat <= 85.0) or not (-180.0 <= lon <= 180.0):
        return None
    return {"lat": round(lat, 8), "lon": round(lon, 8), "rotation": round(rot % 360.0, 3)}


def frames(layout) -> dict:
    """{floor name: {"scale", "cos", "sin", "tx", "ty", "registered", "elevation", "level"}}:
    plan px -> house metres is (x / scale, y / scale) rotated by (cos, sin)
    and shifted by (tx, ty), as registration.to_house does."""
    solved = registration.solve(layout).get("floors", {}) if isinstance(layout, dict) else {}
    out = {}
    for f in (layout or {}).get("floor") or []:
        if not isinstance(f, dict) or not f.get("name"):
            continue
        scale = _num(f.get("scale"))
        if scale is None or scale <= 0:
            continue
        fr = solved.get(f["name"]) or {}
        ok = bool(fr.get("ok"))
        theta = float(fr["theta"]) if ok else 0.0
        out[f["name"]] = {
            "scale": scale, "cos": math.cos(theta), "sin": math.sin(theta),
            "tx": float(fr["tx"]) if ok else 0.0, "ty": float(fr["ty"]) if ok else 0.0,
            "registered": ok, "elevation": registration.elevation(f), "level": _num(f.get("level")),
        }
    return out


def to_house(frame, x_px, y_px) -> list:
    lx, ly = x_px / frame["scale"], y_px / frame["scale"]
    return [round(frame["cos"] * lx - frame["sin"] * ly + frame["tx"], 3),
            round(frame["sin"] * lx + frame["cos"] * ly + frame["ty"], 3)]


def view(layout) -> dict:
    """What the Property view draws, all in house metres: {"site", "frames",
    "floors": [{"name", "level", "elevation", "registered", "rooms": [{"name",
    "points"}], "proxies": [{"slug", "address", "x", "y", "outdoor"}],
    "access_points": [{"mac", "name", "x", "y"}]}]}, floors bottom first."""
    fr = frames(layout)
    floors = []
    for f in (layout or {}).get("floor") or []:
        name = f.get("name") if isinstance(f, dict) else None
        frame = fr.get(name)
        if frame is None:
            continue
        rooms = []
        for z in f.get("zones") or []:
            pts = [to_house(frame, c["x"], c["y"]) for c in z.get("cords") or []
                   if isinstance(c, dict) and _num(c.get("x")) is not None and _num(c.get("y")) is not None]
            if len(pts) >= 3 and not z.get("no_go"):
                rooms.append({"name": z.get("entity_id"), "points": pts})
        rings = [[(p[0], p[1]) for p in r["points"]] for r in rooms]
        proxies = []
        for r in f.get("receivers") or []:
            c = r.get("cords") if isinstance(r, dict) else None
            if isinstance(c, dict) and _num(c.get("x")) is not None and _num(c.get("y")) is not None:
                x, y = to_house(frame, c["x"], c["y"])
                proxies.append({"slug": r.get("entity_id"), "address": r.get("address"), "x": x, "y": y,
                                "outdoor": not any(_inside(x, y, ring) for ring in rings)})
        aps = []
        for a in f.get("access_points") or []:
            c = a.get("cords") if isinstance(a, dict) else None
            if isinstance(c, dict) and _num(c.get("x")) is not None and _num(c.get("y")) is not None and a.get("mac"):
                x, y = to_house(frame, c["x"], c["y"])
                aps.append({"mac": a["mac"], "name": a.get("name"), "x": x, "y": y})
        floors.append({"name": name, "level": frame["level"], "elevation": frame["elevation"], "registered": frame["registered"],
                       "rooms": rooms, "proxies": proxies, "access_points": aps})
    floors.sort(key=lambda f: f["elevation"])
    return {"site": clean_site((layout or {}).get("site")), "frames": fr, "floors": floors}


def _inside(x, y, ring) -> bool:
    inside = False
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
