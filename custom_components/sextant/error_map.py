"""Predicted position error per half-metre square, for the Advice page map.

The prediction is a port of the receiver placement advisor in Hogster/BPS
(custom_components/bps/placement.py, MIT licence, (c) Hogster):

- Ranging noise sigma(d) = d * (a + b*d) * k, fitted on proxy-to-proxy
  pairs: a pair's error is hypot(|ln(median / true)|, std(ln samples)).
  k is how much worse a proxy's own pairs are than the fitted line.
- The error at a point is the Cramer-Rao bound of 2-D ranging,
  sqrt(trace(J^-1)), J = sum(u u^T / sigma^2) over the floor's proxies in
  range: distance, count and spread around the point all count.

The metres are a pessimistic model figure; the colours rank places. Pure
numpy and shapely, so it is testable without Home Assistant.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np
import shapely

from .advice import _rooms_of, _wall_candidates

GRID_M = 0.5
MAX_RANGE_M = 15.0
MIN_D_M = 0.5
ERR_CAP_M = 8.0
DEFAULT_A, DEFAULT_B = 0.6, 0.0     # no calibration pairs to fit on
MIN_PAIRS_FOR_FIT = 8
K_MIN, K_MAX = 0.6, 2.0
JITTER_DEFAULT = 0.3                # ln jitter assumed for 5 samples or fewer
MARGIN_M = 1.0                      # grid margin around the rooms and proxies
STEP_CAP_S = 600.0                  # a longer wait for a thing's next point is not time spent
ROOM_FLOOR_S = 600.0                # every room counts a little, visited or not
MAX_STARS = 2
STAR_GAP_M = 2.0                    # the second star is at least this far from the first
MAX_CELLS = 40_000                  # a bigger floor gets coarser squares: 100 x 100 m stays at GRID_M
MIN_GAIN = 0.03                     # a star must cut the weighted error by this share
CHUNK = 64
CHUNK_CELLS = 250_000      # candidates x cells tried at once: about 30 MB of temporaries
# Measured bad spots, pooled in squares of BAD_CELL_M.
BAD_CELL_M = 1.0
PIN_BAD_M = 3.0                     # a pin read this far off
FLIP_BACK_S, FLIP_NEAR_M = 180.0, 3.0   # off the floor and back, near where it left
JUMP_M, JUMP_BACK_S, JUMP_NEAR_M = 4.0, 60.0, 1.5
GAP_DROPOUT = 2                     # history.GAP_DROPOUT: not heard across this step
MIN_EVENTS, MIN_HOURS = 3, 2        # flips and jumps: repeated, not one bad afternoon


def fit_noise(pairs):
    """Noise line and per-proxy factor from (tx, rx, true_m, samples_m) pairs."""
    used = []
    for tx, rx, true_m, samples in pairs:
        s = [float(v) for v in samples or [] if v and v > 0 and math.isfinite(v)]
        if not true_m or true_m <= 0 or not math.isfinite(true_m) or not s:
            continue
        jit = float(np.std(np.log(s))) if len(s) > 5 else JITTER_DEFAULT
        bias = abs(math.log(float(np.median(s)) / true_m))
        used.append((tx, rx, float(true_m), math.hypot(bias, jit)))
    if len(used) < MIN_PAIRS_FOR_FIT:
        return {"a": DEFAULT_A, "b": DEFAULT_B, "factor": {}, "pairs": len(used), "calibrated": False}
    A = np.array([[1.0, p[2]] for p in used])
    y = np.array([p[3] for p in used])
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)
    a, b = max(float(a), 0.1), max(float(b), 0.0)
    ratios = defaultdict(list)
    for tx, rx, d, err in used:
        r = err / (a + b * d)
        ratios[tx].append(r)
        ratios[rx].append(r)
    factor = {k: float(np.clip(np.median(v), K_MIN, K_MAX)) for k, v in ratios.items()}
    return {"a": a, "b": b, "factor": factor, "pairs": len(used), "calibrated": True}


def _info(gx, gy, proxies, a, b):
    """Fisher terms (j00, j01, j11) and proxies in range (n) at points gx, gy (metres).

    A proxy's x, y may be arrays broadcastable against gx: that tries many
    candidate spots at once.
    """
    j00 = np.zeros(np.broadcast(gx, gy).shape)
    j01 = np.zeros_like(j00)
    j11 = np.zeros_like(j00)
    n = np.zeros_like(j00)
    for px, py, k in proxies:
        dx, dy = px - gx, py - gy
        r = np.hypot(dx, dy)
        d = np.maximum(r, MIN_D_M)          # floors the noise only: the direction stays a unit vector
        sig = d * (a + b * d) * k
        w = np.where(d <= MAX_RANGE_M, 1.0 / sig ** 2, 0.0)
        r = np.where(r > 0, r, 1.0)
        ux, uy = dx / r, dy / r
        j00 = j00 + w * ux * ux
        j01 = j01 + w * ux * uy
        j11 = j11 + w * uy * uy
        n = n + (d <= MAX_RANGE_M)
    return j00, j01, j11, n


def _err(j00, j01, j11, n):
    # Two proxies bound a point on paper, but the solver will not place from fewer than three.
    det = j00 * j11 - j01 ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.sqrt((j00 + j11) / det)
    return np.minimum(np.where(np.isfinite(e) & (n >= 3), e, ERR_CAP_M), ERR_CAP_M)


def _chunk(cells):
    """Candidates tried at once over this many cells: CHUNK, fewer on a big floor."""
    return max(1, min(CHUNK, CHUNK_CELLS // max(1, cells)))


def error_field(gx, gy, proxies, a, b):
    """Predicted error (m) at points gx, gy (metres); proxies [(x, y, k)]."""
    return _err(*_info(gx, gy, proxies, a, b))


def _best_candidate(gx, gy, info, cand_x, cand_y, k_new, w, cur, a, b):
    """Index of the candidate that lowers sum(w * err) most, its gain, its field.

    Vectorised over up to CHUNK candidates at a time: a few hundred numpy
    calls rather than one small call per candidate.
    """
    best_gain, best_i, best_e = -1.0, None, None
    j00, j01, j11, n = info
    step = _chunk(len(gx))
    for s in range(0, len(cand_x), step):
        cx, cy = cand_x[s:s + step, None], cand_y[s:s + step, None]
        n00, n01, n11, nn = _info(gx[None, :], gy[None, :], [(cx, cy, k_new)], a, b)
        e = _err(j00[None, :] + n00, j01[None, :] + n01, j11[None, :] + n11, n[None, :] + nn)
        gains = ((cur[None, :] - e) * w[None, :]).sum(axis=1)
        i = int(np.argmax(gains))
        if gains[i] > best_gain:
            best_gain, best_i, best_e = float(gains[i]), s + i, e[i].copy()
    return best_i, best_gain, best_e


def _grid(rooms, scale):
    """(x0, y0, step, nx, ny) in metres: the rooms' box plus MARGIN_M, at most MAX_CELLS squares.

    Proxies off the rooms do not widen it: the map is drawn inside the rooms only.
    """
    xs = [v / scale for _r, p in rooms for v in p.bounds[0::2]]
    ys = [v / scale for _r, p in rooms for v in p.bounds[1::2]]
    x0, y0 = min(xs) - MARGIN_M, min(ys) - MARGIN_M
    w, h = max(xs) + MARGIN_M - x0, max(ys) + MARGIN_M - y0
    step = GRID_M
    while math.ceil(w / step) * math.ceil(h / step) > MAX_CELLS:
        step *= 2
    return x0, y0, step, int(math.ceil(w / step)), int(math.ceil(h / step))


def _floors(layout):
    """(floor, scale, rooms) for each floor with a scale and at least one room."""
    for floor in (layout or {}).get("floor") or []:
        scale = float(floor.get("scale") or 0)
        rooms = _rooms_of(floor) if scale > 0 else []
        if rooms:
            yield floor, scale, rooms


def room_seconds(layout, tracks):
    """{(floor, room): seconds} from {thing: [(t, floor, x_m, y_m, gap)]}.

    A point's time runs to the thing's next point, capped, and not across a
    break in the track.
    """
    floors = {f.get("name"): (scale, rooms) for f, scale, rooms in _floors(layout)}
    out = defaultdict(float)
    for pts in tracks.values():
        pts = list(pts)
        if len(pts) < 2:
            continue
        t = np.array([p[0] for p in pts], dtype=float)
        fl = np.array([p[1] for p in pts], dtype=object)
        x = np.array([p[2] for p in pts], dtype=float)
        y = np.array([p[3] for p in pts], dtype=float)
        ok = np.array([not p[4] for p in pts[1:]])
        dt = np.minimum(np.diff(t), STEP_CAP_S)
        for name, (scale, rooms) in floors.items():
            on = ok & (fl[:-1] == name)
            if not on.any():
                continue
            px, py, d = x[:-1][on] * scale, y[:-1][on] * scale, dt[on]
            free = np.ones(len(d), dtype=bool)
            for room, poly in rooms:
                inside = free & shapely.contains_xy(poly, px, py)
                if inside.any():
                    out[(name, room)] += float(d[inside].sum())
                    free &= ~inside
    return dict(out)


def floor_map(floor, noise, seconds):
    """Predicted error grid and up to MAX_STARS wall spots for one floor, or None.

    Plan px out: grid x0, y0 is the first cell's centre; err and err_after
    are row-major for every cell of the box (drawing clips to the rooms).
    """
    scale = float(floor.get("scale") or 0)
    rooms = _rooms_of(floor) if scale > 0 else []
    if not rooms:
        return None
    name = floor.get("name")
    a, b, factor = noise["a"], noise["b"], noise.get("factor") or {}
    placed = [(float(r["cords"]["x"]) / scale, float(r["cords"]["y"]) / scale, factor.get(str(r.get("entity_id")), 1.0))
              for r in floor.get("receivers") or [] if isinstance(r.get("cords"), dict) and {"x", "y"} <= r["cords"].keys()]
    x0, y0, step, nx, ny = _grid(rooms, scale)
    GX, GY = np.meshgrid(x0 + step * (np.arange(nx) + 0.5), y0 + step * (np.arange(ny) + 0.5))
    gx, gy = GX.ravel(), GY.ravel()

    room_of = np.full(gx.shape, -1)
    for i, (_room, poly) in enumerate(rooms):
        room_of[(room_of < 0) & shapely.contains_xy(poly, gx * scale, gy * scale)] = i
    w = np.zeros(gx.shape)
    for i, (room, _poly) in enumerate(rooms):
        cells = room_of == i
        if cells.any():
            w[cells] = (seconds.get((name, room), 0.0) + ROOM_FLOOR_S) / cells.sum()
    if w.sum() > 0:
        w /= w.sum()

    info = _info(gx, gy, placed, a, b)
    base = cur = _err(*info)
    k_new = float(np.median(list(factor.values()))) if factor else 1.0
    cands = [(x / scale, y / scale, room) for room, poly in rooms for x, y in _wall_candidates(poly, scale)]
    cand_x, cand_y = np.array([c[0] for c in cands]), np.array([c[1] for c in cands])
    stars = []
    while len(stars) < MAX_STARS and cands and w.sum() > 0:
        i, gain, e = _best_candidate(gx, gy, info, cand_x, cand_y, k_new, w, cur, a, b)
        before = float((w * cur).sum())
        if i is None or gain / before < MIN_GAIN:
            break
        stars.append({"x": round(float(cand_x[i]) * scale, 1), "y": round(float(cand_y[i]) * scale, 1),
                      "room": cands[i][2], "gain_pct": round(100 * gain / before, 1)})
        info = tuple(p + q for p, q in zip(info, _info(gx, gy, [(cand_x[i], cand_y[i], k_new)], a, b)))
        cur = e
        keep = np.hypot(cand_x - cand_x[i], cand_y - cand_y[i]) >= STAR_GAP_M
        cand_x, cand_y, cands = cand_x[keep], cand_y[keep], [c for c, k in zip(cands, keep) if k]
    note = "needs three proxies on this floor before a spot can be chosen" if not stars and len(placed) < 3 else ""
    return {
        "grid": {"x0": round((x0 + step / 2) * scale, 1), "y0": round((y0 + step / 2) * scale, 1),
                 "step": round(step * scale, 3), "w": nx, "h": ny},
        "err": [round(float(v), 1) for v in base],
        "err_after": [round(float(v), 1) for v in cur],
        "stars": stars, "note": note,
    }


def _events(pts):
    """(kind, t, floor, x_m, y_m) for each floor flip and jump in one thing's track."""
    if len(pts) < 3:
        return []
    f = np.array([p[1] for p in pts], dtype=object)
    x = np.array([p[2] for p in pts], dtype=float)
    y = np.array([p[3] for p in pts], dtype=float)
    trig = np.nonzero((f[1:] != f[:-1]) | (np.hypot(np.diff(x), np.diff(y)) >= JUMP_M))[0] + 1
    out = []
    for i in trig:
        t0, f0, x0, y0, _g = pts[i - 1]
        flip = pts[i][1] != f0
        back, near = (FLIP_BACK_S, FLIP_NEAR_M) if flip else (JUMP_BACK_S, JUMP_NEAR_M)
        for j in range(i, len(pts)):   # by index: a slice would copy the rest of the track every time
            tj, fj, xj, yj, gj = pts[j]
            if gj == GAP_DROPOUT or tj - t0 > back:
                break                   # not heard across it, or too slow to be a bounce
            if fj != f0:
                continue
            if math.hypot(xj - x0, yj - y0) <= near:
                out.append(("flip" if flip else "jump", t0, f0, x0, y0))
                break
            if flip:
                break   # back on the floor somewhere else: it walked
    return out


def bad_squares(layout, tracks, pins, weak):
    """{floor: [purple square]} from pins, weak proxies, and flips and jumps in the tracks.

    pins and weak are {entity, floor, x, y (plan px), error_m}; a square is
    {x, y (top-left, plan px), size, kinds: {kind: count}, things, hours}.
    """
    scales = {f.get("name"): scale for f, scale, _rooms in _floors(layout)}
    cells = defaultdict(lambda: {"kinds": Counter(), "things": set(), "hours": set()})

    def add(floor, x_m, y_m, kind, thing, t=None):
        c = cells[(floor, math.floor(x_m / BAD_CELL_M), math.floor(y_m / BAD_CELL_M))]
        c["kinds"][kind] += 1
        c["things"].add(thing)
        if t is not None:
            c["hours"].add(int(t // 3600))

    for kind, items in (("pin", [p for p in pins if (p.get("error_m") or 0) >= PIN_BAD_M]), ("proxy", weak)):
        for p in items:
            scale = scales.get(p.get("floor"))
            if scale:
                add(p["floor"], p["x"] / scale, p["y"] / scale, kind, p["entity"])
    for thing, pts in tracks.items():
        for kind, t, floor, x, y in _events(list(pts)):
            if floor in scales:
                add(floor, x, y, kind, thing, t)
    out = defaultdict(list)
    for (floor, ix, iy), c in sorted(cells.items()):
        k = c["kinds"]
        if not (k["pin"] or k["proxy"] or (k["flip"] + k["jump"] >= MIN_EVENTS and len(c["hours"]) >= MIN_HOURS)):
            continue
        size = BAD_CELL_M * scales[floor]
        out[floor].append({"x": round(ix * size, 1), "y": round(iy * size, 1), "size": round(size, 1),
                           "kinds": dict(+k), "things": sorted(c["things"]), "hours": len(c["hours"])})
    return dict(out)


def floor_maps(layout, pairs, tracks, pins, weak):
    """The Advice page's maps: one noise fit for the house, a map per floor with a scale."""
    noise = fit_noise(pairs)
    tracks = {k: list(v) for k, v in tracks.items()}
    seconds = room_seconds(layout, tracks)
    bad = bad_squares(layout, tracks, pins, weak)
    maps = {}
    for floor in (layout or {}).get("floor") or []:
        m = floor_map(floor, noise, seconds)
        if m is not None:
            maps[floor.get("name")] = {**m, "bad": bad.get(floor.get("name"), [])}
    model = {"a": round(noise["a"], 3), "b": round(noise["b"], 4), "pairs": noise["pairs"], "calibrated": noise["calibrated"]}
    return {"model": model, "maps": maps}
