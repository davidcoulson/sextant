"""Placement advice: which rooms the proxies serve worst, and where a proxy would help.

Pure geometry over the layout plus the self-test result; nothing here reads
Home Assistant. For every room on every floor it combines two views:

* measured: the leave-one-out self-test error of the proxies placed in the
  room (median and worst), which is how well the proxies there are placed
  and heard;
* geometric: for a grid of points inside the room, how far the third-nearest
  proxy on the floor is (a fix needs three) and whether the three nearest
  all sit on one side (a fix between proxies is well conditioned, a fix off
  to one side of them is not).

From those it names an issue per room - no proxy, a weak proxy, poor
coverage, one-sided geometry, or fine - and, for coverage and geometry,
picks wall spots (an outlet or a switch is on a wall) one at a time, each
the spot that best covers what is still uncovered, until the room is
covered or MAX_ADD spots are used.

Each room also carries how much it is used (room_usage, from the person
log): the rooms that need attention are listed most used first.
"""

import math
from collections import Counter

import numpy as np
from shapely.geometry import Point, Polygon

from .replay import bounce_pairs, switches

GRID_M = 0.5            # interior sample spacing
WALL_STEP_M = 0.25      # candidate spacing along the walls
WALL_INSET_M = 0.12     # a wall-mounted proxy sits just inside the wall
TARGET_3RD_M = 5.0      # the third-nearest proxy should be within this of any point
ONE_SIDED_DEG = 300.0   # the three nearest all within a 60-degree cone: one-sided (tuned against rooms that measure well)
COVERED_FRAC = 0.85     # a room is covered when this share of its points pass both tests
MAX_ADD = 2
WEAK_M = 3.0            # a proxy this far off, and twice the room's median, is a weak proxy
GOOD_MEDIAN_M = 2.0     # a room measuring this well gets no coverage advice
USE_STEP_MAX_S = 300.0  # the longest cycle the options allow; a longer wait for a person's next log line is a restart or the log off


def _ring(zone):
    return [(float(c["x"]), float(c["y"])) for c in zone.get("cords", []) if c.get("x") is not None and c.get("y") is not None]


def _largest(geom):
    """The biggest polygon part: repairing a self-crossing room, or insetting
    one with a narrow neck, yields a MultiPolygon, which has no exterior."""
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)
    return geom


def _rooms_of(floor):
    rooms = []
    for zone in floor.get("zones") or []:
        if zone.get("no_go") or len(_ring(zone)) < 3:
            continue
        poly = _largest(Polygon(_ring(zone)).buffer(0))
        if not poly.is_empty and poly.area > 0:
            rooms.append((str(zone.get("entity_id") or zone.get("zone_id")), poly))
    return rooms


def _grid(poly, scale):
    step = GRID_M * scale
    inner = poly.buffer(-0.2 * scale)
    if inner.is_empty:
        inner = poly
    minx, miny, maxx, maxy = poly.bounds
    pts = []
    y = miny + step / 2
    while y < maxy:
        x = minx + step / 2
        while x < maxx:
            if inner.contains(Point(x, y)):
                pts.append((x, y))
            x += step
        y += step
    if not pts:
        c = poly.centroid
        pts = [(c.x, c.y)]
    return np.array(pts, dtype=float)


def _coverage(grid, proxies, scale):
    """Per grid point: third-nearest distance (m) and the largest angular gap (deg) of the three nearest."""
    if len(proxies) < 3:
        return np.full(len(grid), np.inf), np.full(len(grid), 360.0)
    px = np.array(proxies, dtype=float)
    d = np.hypot(grid[:, None, 0] - px[None, :, 0], grid[:, None, 1] - px[None, :, 1]) / scale
    order = np.argsort(d, axis=1)[:, :3]
    d3 = np.take_along_axis(d, order[:, 2:3], axis=1)[:, 0]
    near = px[order]  # (points, 3, 2)
    ang = np.sort(np.degrees(np.arctan2(near[:, :, 1] - grid[:, None, 1], near[:, :, 0] - grid[:, None, 0])), axis=1)
    gaps = np.diff(np.concatenate([ang, ang[:, :1] + 360.0], axis=1), axis=1).max(axis=1)
    return d3, gaps


def _covered_share(grid, proxies, scale):
    d3, gaps = _coverage(grid, proxies, scale)
    ok = (d3 <= TARGET_3RD_M) & (gaps <= ONE_SIDED_DEG)
    return float(ok.mean()), d3, gaps


def _wall_candidates(poly, scale):
    ring = poly.exterior
    inner = _largest(poly.buffer(-WALL_INSET_M * scale))
    out = []
    n = max(4, int(ring.length / (WALL_STEP_M * scale)))
    for i in range(n):
        p = ring.interpolate(i / n, normalized=True)
        if inner.is_empty:
            out.append((p.x, p.y))
            continue
        q = inner.exterior.interpolate(inner.exterior.project(p))
        out.append((q.x, q.y))
    return out


def _suggest(poly, grid, proxies, scale):
    """Greedy wall spots until the room is covered, at most MAX_ADD."""
    have = list(proxies)
    spots = []
    share, _d3, _gaps = _covered_share(grid, have, scale)
    candidates = _wall_candidates(poly, scale)
    while share < COVERED_FRAC and len(spots) < MAX_ADD and candidates:
        best = None
        for c in candidates:
            s, d3, gaps = _covered_share(grid, have + [c], scale)
            # Tie-break on how far the worst point still is from its third proxy.
            key = (s, -float(np.clip(d3, 0, 50).max()))
            if best is None or key > best[0]:
                best = (key, c)
        (s, _), c = best
        if s <= share + 1e-9:
            break  # no wall spot helps any more
        spots.append({"x": round(c[0], 1), "y": round(c[1], 1)})
        have.append(c)
        share = s
    return spots, share


def _stats(errors):
    if not errors:
        return None, None
    arr = np.array(errors, dtype=float)
    return round(float(np.median(arr)), 3), round(float(arr.max()), 3)


def room_usage(lines):
    """How much each room is used, from person log lines (person_log.rows), oldest first.

    {"hours": the span of the lines, "rooms": {(floor, room): (seconds, bounces)}}.
    A line's place holds until the person's next line, so the seconds do not
    depend on how often the cycle ran (the Live page can speed it up). A
    place can be Outside, which is on no plan. A bounce (replay.bounce_pairs)
    counts for both its rooms: the log cannot say which of the two the
    person was in.
    """
    series, prev, secs, first, last = {}, {}, Counter(), None, None
    for r in lines:
        try:
            t, person, place = float(r["t"]), str(r["p"]), r["place"]
            if place is not None:
                room, floor = place
                place = (str(room), str(floor))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue   # from before lines had a place, or not one this integration wrote
        first, last = (t if first is None else first), t
        was = prev.get(person)
        if was and was[1]:
            secs[was[1]] += min(max(t - was[0], 0.0), USE_STEP_MAX_S)
        if not was or was[1] != place:
            # Floor None: a bounce across floors counts too (the place carries its floor).
            series.setdefault(person, []).append((t, None, place))
        prev[person] = (t, place)
    bounced = Counter(p for pair in bounce_pairs(switches(series)) for p in pair)
    return {"hours": 0.0 if first is None else round((last - first) / 3600.0, 1),
            "rooms": {(floor, room): (s, bounced[(room, floor)]) for (room, floor), s in secs.items() if s > 0}}


def advise(layout, selftest, unplaced=None, usage=None):
    """Advice rows, most used of the flagged rooms first, plus the unplaced proxies worth placing.

    ``layout`` is the stored layout, ``selftest`` a run_selftest result (its
    rows carry entity, floor, room, error_m), ``unplaced`` a list of
    {slug, name} for proxies that are heard but placed on no floor,
    ``usage`` a room_usage result. A room's share is of the time spent in
    the rooms listed here, so Outside is in neither side of it. A room the
    usage does not name gets None for its share and bounces: no data is not zero.
    """
    used = (usage or {}).get("rooms") or {}
    solved = [r for r in selftest.get("receivers", []) if isinstance(r.get("error_m"), (int, float))]
    rows = []
    for floor in layout.get("floor", []):
        scale = floor.get("scale")
        if not scale:
            continue
        name = floor.get("name")
        rooms = _rooms_of(floor)
        placed = [(float(r["cords"]["x"]), float(r["cords"]["y"]), str(r.get("entity_id")))
                  for r in floor.get("receivers", []) if isinstance(r.get("cords"), dict)]
        positions = [(x, y) for x, y, _s in placed]
        for room, poly in rooms:
            inside = [s for x, y, s in placed if poly.covers(Point(x, y))]
            errs = {r["entity"]: r["error_m"] for r in solved if r.get("floor") == name and r.get("room") == room}
            median_m, max_m = _stats(list(errs.values()))
            worst = max(errs, key=errs.get) if errs else None
            grid = _grid(poly, scale)
            share, d3, gaps = _covered_share(grid, positions, scale)
            row = {
                "floor": name, "room": room, "area_m2": round(poly.area / scale ** 2, 1),
                "proxies": len(inside), "solved": len(errs), "median_m": median_m, "max_m": max_m,
                "worst": worst, "covered": round(share, 2),
                "third_proxy_m": round(float(np.clip(d3, 0, 99).max()), 1) if len(d3) else None,
                "one_sided": round(float((gaps > ONE_SIDED_DEG).mean()), 2) if len(gaps) else None,
                "add": 0, "spots": [], "issue": "ok", "note": "",
            }
            # Weak proxies: far off, and far off compared with the rest of the
            # room without them (a plain median hides a bad pair among three).
            weak = []
            for slug, e in sorted(errs.items(), key=lambda kv: -kv[1]):
                rest = [v for k, v in errs.items() if k != slug]
                if rest and e >= WEAK_M and e >= 2 * float(np.median(rest)):
                    weak.append(slug)
            poor = share < COVERED_FRAC
            one_sided = row["one_sided"] or 0
            if not inside:
                row["issue"] = "no proxy"
                if poor:
                    row["spots"], _s = _suggest(poly, grid, positions, scale)
                    if not row["spots"]:
                        row["spots"] = [{"x": round(poly.centroid.x, 1), "y": round(poly.centroid.y, 1)}]
                    row["add"] = max(1, len(row["spots"]))
                    row["note"] = "no proxy in this room and the neighbours' do not reach all of it"
                else:
                    row["note"] = "no proxy in this room, but the neighbours' cover it; one here only buys spot-level accuracy"
            elif weak:
                row["issue"] = "weak proxy"
                row["weak"] = weak
                rest = [v for k, v in errs.items() if k not in weak]
                named = ", ".join(f"{w} ({errs[w]:.1f} m)" for w in weak)
                row["note"] = (f"{named} land far from where they are placed, the rest of the room {float(np.median(rest)):.1f} m: "
                               "check they are where the plan shows, and move them off metal and out of cupboards")
                if poor:
                    row["spots"], _s = _suggest(poly, grid, positions, scale)
                    row["add"] = len(row["spots"])
            elif (median_m is None or median_m > GOOD_MEDIAN_M) and poor:
                row["spots"], _s = _suggest(poly, grid, positions, scale)
                row["add"] = len(row["spots"])
                row["issue"] = "one-sided" if one_sided > 0.5 else "coverage"
                row["note"] = (f"the three nearest proxies sit to one side for {one_sided:.0%} of the room"
                               if row["issue"] == "one-sided"
                               else f"the third-nearest proxy is up to {row['third_proxy_m']} m away")
            elif median_m is not None and median_m > GOOD_MEDIAN_M:
                row["issue"] = "noisy"
                row["note"] = (f"covered, yet all {len(errs)} proxies here place about {median_m:.1f} m off: check this floor's scale and "
                               "that each proxy is where the plan shows, and set their mount heights")
                if len(inside) <= 3:
                    # One more opinion helps a room whose few proxies disagree: the wall spot farthest from them.
                    here = [(x, y) for x, y, s in placed if s in inside]
                    cands = _wall_candidates(poly, scale)
                    if cands and here:
                        far = max(cands, key=lambda c: min(math.hypot(c[0] - x, c[1] - y) for x, y in here))
                        row["spots"] = [{"x": round(far[0], 1), "y": round(far[1], 1)}]
                        row["add"] = 1
                        row["note"] += "; a fourth proxy on the far wall gives the room another opinion"
            rows.append(row)
    listed = sum(used[k][0] for k in {(r["floor"], r["room"]) for r in rows} & used.keys())
    for r in rows:
        secs, r["bounces"] = used.get((r["floor"], r["room"]), (None, None))
        r["time_share"] = None if secs is None else round(secs / listed, 3)
    rank = {"no proxy": 0, "weak proxy": 1, "one-sided": 2, "coverage": 2, "noisy": 3, "ok": 4}
    # Rooms that need something first, most used first: poor coverage where
    # people live comes before a closet with no proxy. With no usage this is
    # worst issue first, as it was.
    rows.sort(key=lambda r: (r["issue"] == "ok", -(r["time_share"] or 0), rank[r["issue"]], -(r["median_m"] or 0), r["floor"], r["room"]))
    # Proxies heard but placed nowhere: hand each the next open spot, in the rows' order.
    unplaced = [dict(u) for u in (unplaced or [])]
    open_spots = [(r["floor"], r["room"], s) for r in rows for s in r["spots"]]
    for u, (fl, room, spot) in zip(unplaced, open_spots):
        u["suggest"] = {"floor": fl, "room": room, "x": spot["x"], "y": spot["y"]}
    return {"rooms": rows, "unplaced": unplaced, "usage_hours": (usage or {}).get("hours"),
            "summary": {"rooms": len(rows), "to_add": sum(r["add"] for r in rows),
                        "issues": {k: sum(1 for r in rows if r["issue"] == k) for k in rank if any(r["issue"] == k for r in rows)}}}


# --- where a location pin would help -------------------------------------------

REST_CELL_M = 2.0        # stays are pooled in cells this size: a resting thing's fix wanders about this far
# Four grids, each shifted half a cell: a place on one grid's line sits inside a
# cell of another, so a stay is never split in two and missed.
_REST_GRIDS = ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5))
REST_MIN_HOURS = 2.0     # a place counts once a thing has spent this long there in the history kept
REST_MAX_STEP_S = 600.0  # two points further apart than this are a silence, not a stay
PIN_NEAR_M = 2.0         # a pin this near already covers the place (measured: a pin helps within about 2 m)
REST_PER_THING = 2
REST_MAX_ROWS = 12


def pin_gaps(layout, tracks, pins):
    """Where things rest with no location pin near, most hours first.

    ``tracks`` is {entity: points (t, floor name, x_m, y_m, gap), oldest
    first} from the position history; ``pins`` is {entity: [(floor name,
    x_m, y_m), ...]}, the pins that guide that thing. A row is the thing,
    the floor and room, the place in floor pixels, the hours spent there
    and the nearest pin's distance (None with no pin on the floor). The
    place is where Sextant PUT the thing, so it is only roughly where it
    was: the advice is to pin the thing next time it is there, never to
    pin that point.
    """
    floors = {f.get("name"): f for f in layout.get("floor", []) if f.get("scale")}
    rooms = {name: _rooms_of(f) for name, f in floors.items()}
    rows = []
    for entity, points in tracks.items():
        cells, last = {}, None
        for t, floor, x, y, gap in points:
            # A stay is a step that ends where it began: the time of a trip
            # between two places belongs to neither.
            if (last is not None and not gap and floor == last[1] and 0 < t - last[0] <= REST_MAX_STEP_S
                    and math.hypot(x - last[2], y - last[3]) < REST_CELL_M):
                dt = t - last[0]
                for ox, oy in _REST_GRIDS:
                    acc = cells.setdefault((floor, ox, oy, math.floor(last[2] / REST_CELL_M + ox), math.floor(last[3] / REST_CELL_M + oy)), [0.0, 0.0, 0.0])
                    acc[0] += dt
                    acc[1] += last[2] * dt
                    acc[2] += last[3] * dt
            last = (t, floor, x, y)
        places = []
        for (floor, ox, oy, i, j), (secs, sx, sy) in sorted(cells.items(), key=lambda kv: -kv[1][0]):
            if secs < REST_MIN_HOURS * 3600 or len(places) >= REST_PER_THING:
                break
            if floor not in floors:
                continue
            x, y = sx / secs, sy / secs
            near = min((math.hypot(x - px, y - py) for f, px, py in pins.get(entity) or () if f == floor), default=None)
            # Covered by a pin, or a place already listed, seen through another
            # grid: a cell that overlaps a listed one holds some of the same time.
            cx, cy = (i - ox) * REST_CELL_M, (j - oy) * REST_CELL_M
            if (near is not None and near < PIN_NEAR_M) or any(
                    f == floor and (math.hypot(x - px, y - py) < PIN_NEAR_M or (abs(cx - qx) < REST_CELL_M and abs(cy - qy) < REST_CELL_M))
                    for f, px, py, qx, qy in places):
                continue
            places.append((floor, x, y, cx, cy))
            scale = floors[floor]["scale"]
            at = Point(x * scale, y * scale)
            rows.append({
                "entity": entity, "floor": floor, "room": next((name for name, poly in rooms[floor] if poly.covers(at)), None),
                "x": round(at.x, 1), "y": round(at.y, 1), "hours": round(secs / 3600, 1),
                "nearest_pin_m": None if near is None else round(near, 1),
            })
    rows.sort(key=lambda r: -r["hours"])
    return rows[:REST_MAX_ROWS]
