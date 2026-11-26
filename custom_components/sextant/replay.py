"""Replay the room election over the election log with other tuning values.

What a tuning change would have done to the last hours: how many room
switches and bounces, against what the same replay gives with the tuning as
it is. tools/replay_rooms.py is the workbench this came from.

It is an estimate. The log has no Kalman covariance, so the filter's
uncertainty is stood in for by a circle of SIGMA_K * rms_m; a floor challenge
(hold) is not logged, so the switches it deferred are allowed; and habits are
read as they are now and not learned. ``agree`` says how well the replay at
the current tuning reproduces what was published: judge the rest by it.

Runs in an executor. The election runs on a copy of ``_elect_zone`` bound to
its own state, so nothing the live loop reads is touched from the thread.
"""
import copy
import json
import os
import time
import types

import numpy as np
from shapely import make_valid
from shapely.geometry import Point, Polygon

from . import election_log

SIGMA_K = 0.5
BOUNCE_WINDOW_S = 120.0
# The knobs the room election reads, so the only ones worth replaying.
ROOM_KEYS = (
    "zone_prob_smoothing", "zone_switch_margin", "zone_switch_secs", "stationary_speed", "stationary_secs",
    "zone_lock_warmup_secs", "zone_unlock_margin", "zone_unlock_secs", "far_move_margin", "far_move_secs",
    "zone_anchor_inset_m", "habit_margin_gain",
)


def load_rows(dirpath: str, hours: float, now: float | None = None) -> list:
    """The log's rows from the last ``hours`` that the room election can replay, oldest first."""
    since = (time.time() if now is None else now) - hours * 3600.0
    rows = []
    for r in election_log.iter_rows(dirpath, since):
        if r.get("cords") and r.get("floor") and r.get("zone_raw"):
            rows.append({k: r.get(k) for k in ("t", "ent", "floor", "cords", "zone_raw", "zone", "anchor", "rms_m", "speed")})
    rows.sort(key=lambda r: r["t"])
    return rows


def _floors(core, layout):
    """{floor: (zone polygons, scale)} and {proxy: Point}, as the live loop builds them."""
    floors, proxies = {}, {}
    for f in layout.get("floor") or []:
        polys = []
        for z in f.get("zones") or []:
            c = z.get("cords") or []
            if len(c) < 3:
                continue
            p = Polygon([(q["x"], q["y"]) for q in c])
            if not p.is_valid:
                p = make_valid(p)
            polys.append((z["entity_id"], p, 0.0, bool(z.get("no_go"))))
        floors[f.get("name")] = (core._FloorZones(polys), f.get("scale"))
        for rx in f.get("receivers") or []:
            c = rx.get("cords") or {}
            if c.get("x") is not None and c.get("y") is not None:
                proxies[str(rx.get("entity_id"))] = Point(c["x"], c["y"])
    return floors, proxies


def _elector(core, habits_now):
    """``_elect_zone`` on its own state: fresh zone state, the habits as given, nothing learned."""
    habits = types.SimpleNamespace(**{k: getattr(core.habits_mod, k) for k in dir(core.habits_mod) if not k.startswith("__")})
    habits.learn = lambda *a, **k: None
    scope = {**vars(core), "_zone_state": {}, "_habits": copy.deepcopy(habits_now), "_habits_last": {}, "habits_mod": habits}
    return types.FunctionType(core._elect_zone.__code__, scope, "_elect_zone", core._elect_zone.__defaults__)


def run(core, layout, rows, tuning=None, habits=None) -> dict:
    """{thing: [(t, floor, room)]}: the rooms the election would publish with ``tuning`` laid over the layout's."""
    lay = {**layout, "tuning": {**(layout.get("tuning") or {}), **(tuning or {})}}
    floors, proxies = _floors(core, lay)
    elect = _elector(core, core._habits if habits is None else habits)
    out = {}
    for r in rows:
        if r["floor"] not in floors:
            continue
        polys, scale = floors[r["floor"]]
        if not isinstance(scale, (int, float)) or scale <= 0:
            continue
        x, y = r["cords"]
        anchor = proxies.get(str(r["anchor"])) if r.get("anchor") is not None else None
        kf = None
        if r.get("anchor") is None:
            sig = max(0.05, (r.get("rms_m") or 1.0) * SIGMA_K) * scale
            kf = {"floor": r["floor"], "P": np.diag([sig * sig, sig * sig, 1.0, 1.0]),
                  "x": np.array([x, y, (r.get("speed") or 0.0) * scale, 0.0])}
        zone, _locked, _speed = elect(r["ent"], r["floor"], r["zone_raw"], Point(x, y), kf, polys, scale, lay, now=r["t"], anchor_point=anchor,
                                     closed=set(r.get("closed") or ()))
        out.setdefault(r["ent"], []).append((r["t"], r["floor"], zone))
    return out


def logged(rows) -> dict:
    out = {}
    for r in rows:
        out.setdefault(r["ent"], []).append((r["t"], r["floor"], r.get("zone")))
    return out


def switches(series) -> list:
    """(thing, t, from, to) for each room change on one floor."""
    return [(e, t1, z0, z1) for e, s in series.items()
            for (_t0, f0, z0), (t1, f1, z1) in zip(s, s[1:]) if f0 == f1 and z0 != z1 and z0 and z1]


def bounce_pairs(sw) -> list:
    """(A, B) for each switch undone within BOUNCE_WINDOW_S: A to B and straight back."""
    by = {}
    for e, t, a, b in sw:
        by.setdefault(e, []).append((t, a, b))
    return [(a0, b0) for lst in by.values() for (t0, a0, b0), (t1, a1, b1) in zip(lst, lst[1:])
            if b1 == a0 and a1 == b0 and t1 - t0 <= BOUNCE_WINDOW_S]


def bounces(sw) -> int:
    return len(bounce_pairs(sw))


def _same(a, b) -> float | None:
    same = total = 0
    for e, s in a.items():
        for (_t, _f, z), (_t2, _f2, z2) in zip(s, b.get(e, [])):
            total += 1
            same += z == z2
    return round(same / total, 4) if total else None


def _stats(series) -> dict:
    sw = switches(series)
    return {"switches": len(sw), "bounces": bounces(sw)}


def compare(core, layout, rows, tuning, habits=None) -> dict:
    """The replay with the tuning as it is and with ``tuning`` laid over it, side by side.

    ``habits`` is a copy of the learned habits taken on the event loop: the live dict changes there."""
    # Only rows run() will replay, so the three series line up row for row.
    ok = {f.get("name") for f in layout.get("floor") or [] if isinstance(f.get("scale"), (int, float)) and f["scale"] > 0}
    rows = [r for r in rows if r["floor"] in ok]
    if not rows:
        return {"rows": 0}
    base, trial, pub = run(core, layout, rows, habits=habits), run(core, layout, rows, tuning, habits), logged(rows)
    per = {}
    for e in base:
        b, t = _stats({e: base[e]}), _stats({e: trial.get(e, [])})
        if b != t:
            per[e] = {"base": b, "trial": t}
    return {
        "rows": len(rows), "things": len(base), "hours": round((rows[-1]["t"] - rows[0]["t"]) / 3600.0, 1),
        "logged": _stats(pub), "base": {**_stats(base), "agree": _same(base, pub)},
        "trial": {**_stats(trial), "same_as_base": _same(trial, base)},
        "things_changed": dict(sorted(per.items(), key=lambda kv: -abs(kv[1]["trial"]["switches"] - kv[1]["base"]["switches"]))[:8]),
    }
