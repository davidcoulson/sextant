#!/usr/bin/env python3
"""
Would borrowing the other floors' proxies have placed things better?

While the election log records, each floor's entry in ``floor_cands`` carries
``cross``: the fix that floor would have had with the other floors' proxies
helping, and ``own``, the same solve without them. Nothing is placed by
``cross``; this reads the log and says which of the two was the better fix on
the floor that was elected, by three measures that need no ground truth:

``still``   median step between consecutive fixes while the thing was not
            moving (m). Lower is steadier. Precision, not accuracy.
``in room`` share of fixes inside the room that was published. The published
            room comes from the real fix, so this leans towards ``own``.
``anchor``  median distance to the proxy the thing was sitting on (m), for
            the cycles it was anchored. The only real truth in the log.

``moved`` is the median distance between the two fixes. Rows logged before
``own`` existed are compared against the published floor fix instead, which
is fused with the fingerprint where that is on; they are only used while the
log has none of the newer rows.

Usage::

    python tools/replay_cross_floor.py config/sextant_election_log --layout config/.storage/sextant
    python tools/replay_cross_floor.py log/ --layout layout.json --hours 48 --things
"""

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import math
import os
import statistics

STILL_SPEED = 0.1   # m/s
STILL_GAP_S = 60.0  # consecutive cycles, not the two ends of a silence


def load_rows(path, hours=None):
    files = sorted(f for f in glob.glob(os.path.join(path, "*.jsonl*")) if not f.endswith(".tmp")) if os.path.isdir(path) else [path]
    rows = []
    for name in files:
        with (gzip.open(name, "rt", encoding="utf-8") if name.endswith(".gz") else open(name, encoding="utf-8")) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue  # a line cut short by a restart
                if isinstance(r, dict) and r.get("ent") and r.get("t") is not None:
                    rows.append(r)
    rows.sort(key=lambda r: r["t"])
    if hours and rows:
        rows = [r for r in rows if r["t"] >= rows[-1]["t"] - hours * 3600.0]
    return rows


def load_layout(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("data", data)  # the .storage file wraps the layout in "data"


def inside(poly, x, y):
    """Point in polygon (ray casting); ``poly`` is [(x, y), ...]."""
    hit = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            hit = not hit
    return hit


def floors_of(layout):
    """Per floor: scale, room outlines and proxy positions."""
    out = {}
    for f in layout.get("floor", []):
        out[f.get("name")] = {
            "scale": float(f.get("scale") or 0) or None,
            # Drawn outlines only: an old two-corner rectangle is stored in scan order.
            "rooms": {z.get("entity_id"): [(c["x"], c["y"]) for c in z.get("cords", [])]
                      for z in f.get("zones", []) if z.get("poly") and len(z.get("cords", [])) >= 3},
            "rx": {r.get("entity_id"): (r["cords"]["x"], r["cords"]["y"])
                   for r in f.get("receivers", []) if "x" in r.get("cords", {}) and "y" in r.get("cords", {})},
        }
    return out


def pairs(rows, floors):
    """Per thing, the cycles that have both fixes: (row, floor info, own, cross, like_for_like, seq).

    ``seq`` counts every row the thing logged, so two cycles with a dropped
    one between them (it moved, or changed floor) are not taken as neighbours.
    Once any row carries ``own``, the older rows without it are left out.
    """
    out, seq = collections.defaultdict(list), collections.Counter()
    for r in rows:
        seq[r["ent"]] += 1
        cand = (r.get("floor_cands") or {}).get(r.get("floor")) or {}
        cross, info = cand.get("cross"), floors.get(r.get("floor"))
        if not cross or not info or not info["scale"]:
            continue
        own = cross.get("own") or cand.get("fix")
        if own:
            out[r["ent"]].append((r, info, own, cross["fix"], "own" in cross, seq[r["ent"]]))
    if any(c[4] for cycles in out.values() for c in cycles):
        out = {ent: [c for c in cycles if c[4]] for ent, cycles in out.items()}
    return {ent: cycles for ent, cycles in out.items() if cycles}


def measure(cycles):
    """The three measures for one thing's cycles, own and cross side by side."""
    moved, still, room, anchor = [], ([], []), ([], []), ([], [])
    prev = None
    for r, info, own, cross, _like, seq in cycles:
        m = info["scale"]
        moved.append(math.dist(own, cross) / m)
        slow = r.get("speed") is not None and r["speed"] <= STILL_SPEED
        if prev and slow and prev[3] == seq - 1 and prev[0]["ent"] == r["ent"] and prev[0]["floor"] == r["floor"] \
                and 0 < r["t"] - prev[0]["t"] <= STILL_GAP_S:
            still[0].append(math.dist(own, prev[1]) / m)
            still[1].append(math.dist(cross, prev[2]) / m)
        prev = (r, own, cross, seq) if slow else None
        poly = info["rooms"].get(r.get("zone"))
        if poly:
            room[0].append(inside(poly, *own))
            room[1].append(inside(poly, *cross))
        at = info["rx"].get(r.get("anchor"))
        if at:
            anchor[0].append(math.dist(own, at) / m)
            anchor[1].append(math.dist(cross, at) / m)
    med = lambda v: statistics.median(v) if v else None
    share = lambda v: sum(v) / len(v) if v else None
    return {
        "n": len(cycles), "like": sum(1 for c in cycles if c[4]), "moved": med(moved),
        "still": (med(still[0]), med(still[1]), len(still[0])),
        "room": (share(room[0]), share(room[1]), len(room[0])),
        "anchor": (med(anchor[0]), med(anchor[1]), len(anchor[0])),
    }


def _cell(pair, fmt):
    """own, cross and a '<' where cross did better: smaller in metres, larger as a share."""
    a, b, n = pair
    if a is None:
        return f"{'-':>20}"
    better = b < a if fmt is _m else b > a
    return f"{fmt(a):>5} {fmt(b):>5} {'<' if better else ' '} {f'({n})':>7}"


def _m(v):
    return f"{v:.2f}"


def _pct(v):
    return f"{v * 100:.0f}%"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log", help="the election log directory, or one of its files")
    ap.add_argument("--layout", required=True, help="the layout (config/.storage/sextant or a snapshot)")
    ap.add_argument("--hours", type=float, help="only the last N hours of the log")
    ap.add_argument("--things", action="store_true", help="a line per thing as well as per class")
    args = ap.parse_args(argv)
    layout = load_layout(args.layout)
    by_thing = pairs(load_rows(args.log, args.hours), floors_of(layout))
    classes = layout.get("thing_classes") or {}
    by_class = collections.defaultdict(dict)
    for ent, cycles in by_thing.items():
        by_class[classes.get(ent, "other")][ent] = cycles
    lines = []
    for cls in sorted(by_class):
        # Sorted by thing then time, so a "still" step never spans two things (the gap test does the rest).
        lines.append((cls, sorted((c for cycles in by_class[cls].values() for c in cycles), key=lambda c: (c[0]["ent"], c[0]["t"]))))
        if args.things:
            lines.extend((f"  {ent}", by_class[cls][ent]) for ent in sorted(by_class[cls]))
    everything = sorted((c for cycles in by_thing.values() for c in cycles), key=lambda c: (c[0]["ent"], c[0]["t"]))
    lines.append(("ALL", everything))
    print(f"{'':28}{'cycles':>7} {'moved':>6}   {'still own/cross (n)':>20}   {'room own/cross (n)':>20}   {'anchor own/cross (n)':>20}")
    for name, cycles in lines:
        s = measure(cycles)
        print(f"{name[:27]:28}{s['n']:>7} {_m(s['moved']):>6}   {_cell(s['still'], _m)}   {_cell(s['room'], _pct)}   {_cell(s['anchor'], _m)}")
    total, like = len(everything), sum(1 for c in everything if c[4])
    print("\n'<' marks the measure where cross did better; (n) is how many cycles it rests on. The anchor is itself")
    print("inferred from signal strength, and the room from the published fix: evidence, not ground truth.")
    if like < total:
        print("These rows predate the logged geometric fix: 'own' here is the published floor fix, fused where that is on.")


if __name__ == "__main__":
    main()
