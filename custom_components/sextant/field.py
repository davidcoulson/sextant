"""The Wi-Fi signal field: a continuous estimate per floor, not just the
squares someone has stood in.

heat.py keeps what was measured: the signal clients got, pooled in one-metre
squares. Between the squares there is nothing, and a house is mostly between
the squares. This module fills it in, honestly:

1. **A model per access point.** From where the access point is placed, the
   signal falls with the log of the distance (``P - 10 n log10 d``), loses a
   fixed amount for each wall the straight line crosses (the room outlines
   stand in for walls) and a fixed amount for each floor it goes through.
   Each access point gets its own level at a metre (``P``) and fall-off
   (``n``), fitted to the squares measured on it; the wall and floor losses
   are shared by all of them. Priors keep a thinly measured access point near
   ordinary values instead of letting three samples decide it.
2. **Corrected by the measurements.** Near the squares, what was measured
   pulls the model to the truth (a Gaussian-weighted residual that shrinks to
   nothing away from them).
3. **Says how sure it is.** Every point carries a confidence from how far the
   nearest measured square is; the map fades what is only the model.

Computed on a half-metre grid: the BLE fixes that place the phones are good
to a metre or two, so a finer grid would only be finer noise. The page
interpolates it down to 10 cm for drawing.

Pure: numpy, no Home Assistant. __init__ gives it the layout and the squares.
"""
from __future__ import annotations

import math

import numpy as np

from . import registration

GRID_M = 0.5
# Distances under this are this (the formula runs off to +inf at the antenna).
MIN_D_M = 0.5
# Priors: the value, and how strongly it holds (in the same units as a
# square's weight, the root of its samples). Strong on purpose. Most squares
# are fixed proxies of mixed hardware, one square each for good, so a
# device's own transmit strength (+-10 dB between models) cannot be told
# apart from where it is: fitted freely on the house's data (2026-10-08) the
# fall-off went to its floor, walls to 1 dB and a floor to 3, for a fit only
# 0.4 dB better than this. Not stronger: a prior of 30 overrode a clean 7 dB
# wall in fifty well-sampled squares. The measured squares still win where
# they are, through the correction.
PRIOR_P_DBM, PRIOR_P_WEIGHT = -38.0, 2.0
PRIOR_N, PRIOR_N_WEIGHT = 3.0, 15.0
PRIOR_WALL_DB, PRIOR_WALL_WEIGHT = 4.0, 10.0
PRIOR_FLOOR_DB, PRIOR_FLOOR_WEIGHT = 15.0, 15.0
BOUNDS = {"n": (1.5, 5.0), "wall": (0.0, 12.0), "floor": (0.0, 35.0), "p": (-70.0, -10.0)}
# A square's weight is the square root of its samples, up to this many: a
# proxy that has sat in one square all week must not outvote the house.
MAX_WEIGHT_SAMPLES = 25
# Two edges crossed within this of each other along the line are one wall
# (two rooms drawn against each other share it, as two edges).
WALL_MERGE_M = 0.3
# The residual correction: how far a measured square reaches, and how much it
# is trusted against the model (the shrink, in the same units as the weights).
# A square stands for about a metre of floor: wider than this and one odd
# square (behind the fridge) is averaged away into its neighbours.
RESIDUAL_SIGMA_M = 0.6
RESIDUAL_SHRINK = 0.3
# Confidence 1 at a measured square, about a third at this distance from one.
CONFIDENCE_M = 4.0
# The page only needs an access point where it is best or second best.
KEEP_RANKS = 2
FLOOR_DBM = -100.0


def _floor_rooms_m(floor, scale):
    """[ring in floor metres] for each room (no-go areas are not rooms)."""
    rings = []
    for z in floor.get("zones") or []:
        if not isinstance(z, dict) or z.get("no_go"):
            continue
        ring = [(float(c["x"]) / scale, float(c["y"]) / scale) for c in z.get("cords") or []
                if isinstance(c, dict) and isinstance(c.get("x"), (int, float)) and isinstance(c.get("y"), (int, float))]
        if len(ring) >= 3:
            if not z.get("poly") and len(ring) == 4:
                cx, cy = sum(p[0] for p in ring) / 4, sum(p[1] for p in ring) / 4
                ring.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
            rings.append(ring)
    return rings


def _edges(rings):
    """(E, 4) array of wall segments x1 y1 x2 y2, in the rings' frame."""
    segs = [(a[0], a[1], b[0], b[1]) for ring in rings for a, b in zip(ring, ring[1:] + ring[:1])]
    return np.array(segs, dtype=float).reshape(-1, 4)


def _floor_edges(floor, to_house):
    """A floor's room outlines as wall segments in the house frame."""
    scale = float(floor["scale"])
    rings = [[tuple(float(v) for v in to_house(px * scale, py * scale)) for px, py in ring] for ring in _floor_rooms_m(floor, scale)]
    return _edges(rings)


def walls_crossed(ax, ay, px, py, edges):
    """How many walls each straight line from (ax, ay) to the points (px, py)
    crosses: edge intersections, those within WALL_MERGE_M of each other along
    the line counted once. px, py: arrays; returns an int array."""
    px, py = np.atleast_1d(np.asarray(px, float)), np.atleast_1d(np.asarray(py, float))
    if not len(edges):
        return np.zeros(px.shape, dtype=int)
    dx, dy = px - ax, py - ay                                   # (P,)
    ex1, ey1, ex2, ey2 = (edges[:, i][None, :] for i in range(4))   # (1, E)
    fx, fy = ex2 - ex1, ey2 - ey1
    den = dx[:, None] * fy - dy[:, None] * fx                   # (P, E)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = ((ex1 - ax) * fy - (ey1 - ay) * fx) / den           # along the line, 0..1
        u = ((ex1 - ax) * dy[:, None] - (ey1 - ay) * dx[:, None]) / den   # along the edge, 0..1
    hit = (np.abs(den) > 1e-12) & (t > 1e-9) & (t < 1 - 1e-9) & (u >= 0) & (u <= 1)
    length = np.hypot(dx, dy)
    out = np.zeros(px.shape, dtype=int)
    for i in np.nonzero(hit.any(axis=1))[0]:
        ts = np.sort(t[i][hit[i]]) * length[i]
        out[i] = 1 + int(np.count_nonzero(np.diff(ts) > WALL_MERGE_M))
    return out


def _house(scale, cos_t, sin_t, tx, ty):
    """A plan-px -> house-metres function for one floor, for numbers or arrays
    alike (registration.to_house, which takes one point at a time)."""
    def to_house(x, y):
        lx, ly = np.asarray(x, float) / scale, np.asarray(y, float) / scale
        return cos_t * lx - sin_t * ly + tx, sin_t * lx + cos_t * ly + ty
    return to_house


def _frames(layout):
    """{floor name: (to_house(x_px, y_px) -> (hx, hy), elevation, rank, registered)}.

    A floor the pins do not register is its own frame (its own metres): its
    access points still model it, the other floors' do not reach it."""
    solved = registration.solve(layout).get("floors", {})
    floors = [f for f in layout.get("floor") or [] if isinstance(f, dict) and f.get("name")]
    order = sorted(floors, key=lambda f: registration.elevation(f))
    out = {}
    for rank, f in enumerate(order):
        scale = f.get("scale")
        if not isinstance(scale, (int, float)) or isinstance(scale, bool) or scale <= 0:
            continue
        fr = solved.get(f["name"])
        if fr and fr.get("ok"):
            conv = _house(float(scale), math.cos(fr["theta"]), math.sin(fr["theta"]), fr["tx"], fr["ty"])
            out[f["name"]] = (conv, registration.elevation(f), rank, True)
        else:
            out[f["name"]] = (_house(float(scale), 1.0, 0.0, 0.0, 0.0), registration.elevation(f), rank, False)
    return out


def _sites(layout, frames):
    """{ap mac: (floor, hx, hy, z, rank, registered)} for the placed access points."""
    from .wifi import placed_access_points  # noqa: PLC0415

    out = {}
    for mac, p in placed_access_points(layout).items():
        fr = frames.get(p["floor"])
        if fr is None:
            continue
        hx, hy = fr[0](p["x"], p["y"])
        out[mac] = (p["floor"], float(hx), float(hy), fr[1], fr[2], fr[3])
    return out


def _reaches(site, floor_name, frames):
    """Whether this access point's model applies on that floor: its own floor
    always; another only when both are in the house frame."""
    fr = frames.get(floor_name)
    return fr is not None and (site[0] == floor_name or (site[5] and fr[3]))


def fit(layout, squares):
    """The model's parameters from the measured squares.

    ``squares``: [(floor, x_px, y_px, ap, dbm, n)] - each square's centre and
    the mean signal it got from one access point. Returns {"aps": {mac: {"p",
    "n", "samples", "rms"}}, "wall", "floor", "rms", "used"}, or None when no
    access point is placed."""
    frames = _frames(layout)
    sites = _sites(layout, frames)
    if not sites:
        return None
    macs = sorted(sites)
    col = {m: i for i, m in enumerate(macs)}
    na = len(macs)
    rows, ys, ws, per_ap = [], [], [], {m: [] for m in macs}
    edges_by_floor = {}
    for floor, x, y, ap, dbm, n in squares:
        site = sites.get(ap)
        if site is None or not _reaches(site, floor, frames):
            continue
        to_house, z, rank, _reg = frames[floor]
        hx, hy = (float(v) for v in to_house(x, y))
        d = max(math.sqrt((hx - site[1]) ** 2 + (hy - site[2]) ** 2 + (z - site[3]) ** 2), MIN_D_M)
        if floor not in edges_by_floor:
            f = next(f for f in layout["floor"] if f.get("name") == floor)
            edges_by_floor[floor] = _floor_edges(f, to_house)
        w = int(walls_crossed(site[1], site[2], [hx], [hy], edges_by_floor[floor])[0])
        floors_between = abs(rank - site[4])
        row = np.zeros(2 * na + 2)
        row[col[ap]] = 1.0                           # P_a
        row[na + col[ap]] = -10.0 * math.log10(d)    # n_a
        row[2 * na] = -float(w)                      # wall loss
        row[2 * na + 1] = -float(floors_between)     # floor loss
        weight = math.sqrt(min(max(float(n), 1.0), MAX_WEIGHT_SAMPLES))
        rows.append(row * weight)
        ys.append(float(dbm) * weight)
        ws.append(weight)
        per_ap[ap].append((row, float(dbm)))
    # Priors, as extra rows.
    for m in macs:
        for idx, value, weight in ((col[m], PRIOR_P_DBM, PRIOR_P_WEIGHT), (na + col[m], PRIOR_N, PRIOR_N_WEIGHT)):
            row = np.zeros(2 * na + 2)
            row[idx] = weight
            rows.append(row)
            ys.append(value * weight)
    for idx, value, weight in ((2 * na, PRIOR_WALL_DB, PRIOR_WALL_WEIGHT), (2 * na + 1, PRIOR_FLOOR_DB, PRIOR_FLOOR_WEIGHT)):
        row = np.zeros(2 * na + 2)
        row[idx] = weight
        rows.append(row)
        ys.append(value * weight)
    theta, *_ = np.linalg.lstsq(np.vstack(rows), np.array(ys), rcond=None)
    clip = lambda v, k: float(min(max(v, BOUNDS[k][0]), BOUNDS[k][1]))   # noqa: E731
    params = {m: {"p": clip(theta[col[m]], "p"), "n": clip(theta[na + col[m]], "n")} for m in macs}
    wall, floor_db = clip(theta[2 * na], "wall"), clip(theta[2 * na + 1], "floor")
    sq_all = []
    for m in macs:
        res = []
        for row, dbm in per_ap[m]:
            pred = params[m]["p"] + params[m]["n"] * row[na + col[m]] + wall * row[2 * na] + floor_db * row[2 * na + 1]
            res.append(dbm - pred)
        params[m]["samples"] = len(res)
        params[m]["rms"] = round(math.sqrt(sum(r * r for r in res) / len(res)), 1) if res else None
        sq_all += [r * r for r in res]
        params[m]["p"], params[m]["n"] = round(params[m]["p"], 1), round(params[m]["n"], 2)
    return {"aps": params, "wall": round(wall, 1), "floor": round(floor_db, 1),
            "rms": round(math.sqrt(sum(sq_all) / len(sq_all)), 1) if sq_all else None, "used": len(sq_all)}


def predict(layout, model, floor_name, xs_px, ys_px, mac):
    """The model's signal from one access point at plan points of one floor
    (arrays in px), before any correction; None when it does not reach."""
    frames = _frames(layout)
    sites = _sites(layout, frames)
    site, params = sites.get(mac), (model or {}).get("aps", {}).get(mac)
    floor = next((f for f in layout.get("floor") or [] if f.get("name") == floor_name), None)
    if site is None or params is None or floor is None or not _reaches(site, floor_name, frames):
        return None
    return _predict(frames, site, params, model, floor, np.asarray(xs_px, float), np.asarray(ys_px, float))


def _predict(frames, site, params, model, floor, xs, ys):
    to_house, z, rank, _reg = frames[floor["name"]]
    hx, hy = to_house(xs, ys)
    d = np.maximum(np.sqrt((hx - site[1]) ** 2 + (hy - site[2]) ** 2 + (z - site[3]) ** 2), MIN_D_M)
    edges = _floor_edges(floor, to_house)
    walls = walls_crossed(site[1], site[2], hx.ravel(), hy.ravel(), edges).reshape(hx.shape)
    return params["p"] - 10.0 * params["n"] * np.log10(d) - model["wall"] * walls - model["floor"] * abs(rank - site[4])


def grid(layout, model, floor_name, squares):
    """One floor's field for the page, or None (no scale, no rooms, no model).

    {"x0", "y0": the first point's plan px; "step": px between points; "w",
    "h": points across and down; "aps": [mac]; "values": {mac: [dBm, row by
    row]} (model plus the correction near what was measured, rounded to the
    dB); "conf": [0-100]}. ``squares`` as for fit, every floor's."""
    floor = next((f for f in layout.get("floor") or [] if isinstance(f, dict) and f.get("name") == floor_name), None)
    if model is None or floor is None or not isinstance(floor.get("scale"), (int, float)) or floor["scale"] <= 0:
        return None
    scale = float(floor["scale"])
    rings = _floor_rooms_m(floor, scale)
    if not rings:
        return None
    xs_m = [p[0] for r in rings for p in r]
    ys_m = [p[1] for r in rings for p in r]
    x0, y0 = math.floor(min(xs_m) / GRID_M) * GRID_M, math.floor(min(ys_m) / GRID_M) * GRID_M
    w = int(math.ceil((max(xs_m) - x0) / GRID_M)) + 1
    h = int(math.ceil((max(ys_m) - y0) / GRID_M)) + 1
    gx, gy = np.meshgrid(x0 + GRID_M * np.arange(w), y0 + GRID_M * np.arange(h))   # floor metres
    px, py = gx * scale, gy * scale
    frames = _frames(layout)
    sites = _sites(layout, frames)
    here = [(x / scale, y / scale, ap, dbm) for f, x, y, ap, dbm, _n in squares if f == floor_name]
    values = {}
    for mac in sorted(sites):
        params = model["aps"].get(mac)
        if params is None or not _reaches(sites[mac], floor_name, frames):
            continue
        field = _predict(frames, sites[mac], params, model, floor, px, py)
        # The correction: this access point's measured squares on this floor,
        # each pulling the field by its residual, fading with distance.
        mine = [(x, y, dbm) for x, y, ap, dbm in here if ap == mac]
        if mine:
            mx, my, md = (np.array(v, float) for v in zip(*mine))
            at = _predict(frames, sites[mac], params, model, floor, mx * scale, my * scale)
            resid = md - at
            k = np.exp(-(((gx[..., None] - mx) ** 2 + (gy[..., None] - my) ** 2) / (2 * RESIDUAL_SIGMA_M ** 2)))
            field = field + (k * resid).sum(-1) / (k.sum(-1) + RESIDUAL_SHRINK)
        values[mac] = np.clip(field, FLOOR_DBM, -10.0)
    if not values:
        return None
    # Keep an access point only where it is among the best few somewhere.
    stack = np.stack([values[m] for m in sorted(values)])
    order = np.argsort(-stack, axis=0)[:KEEP_RANKS]
    keep = {sorted(values)[i] for i in np.unique(order)}
    if here:
        hx_, hy_ = np.array([s[0] for s in here]), np.array([s[1] for s in here])
        dmin = np.sqrt(((gx[..., None] - hx_) ** 2 + (gy[..., None] - hy_) ** 2).min(-1))
        conf = np.exp(-(dmin / CONFIDENCE_M) ** 2)
    else:
        conf = np.zeros(gx.shape)
    return {"x0": round(x0 * scale, 2), "y0": round(y0 * scale, 2), "step": round(GRID_M * scale, 3), "w": w, "h": h,
            "aps": sorted(keep),
            "values": {m: [int(round(v)) for v in values[m].ravel()] for m in sorted(keep)},
            "conf": [int(round(100 * c)) for c in conf.ravel()]}
