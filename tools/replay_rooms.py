"""Replay the ROOM election (the real _elect_zone, lifted from __init__.py) over the election log.

The log has no Kalman covariance, so the filter's uncertainty is stood in for by a circle of
sigma_k * rms_m; the first run checks how well that reproduces the published rooms at the live settings.
usage: replay_rooms.py <sextant __init__.py> <layout.json> <log dir>
"""
import ast, glob, gzip, json, math, sys, types, statistics
import numpy as np
import shapely
from shapely.geometry import Point, Polygon

src_path, layout_path, log_dir = sys.argv[1:4]
src = open(src_path).read()
tree = ast.parse(src)
WANT_FN = {"_step_weight", "_new_zone_state", "_covariance_samples", "_zone_membership", "_far_move", "_elect_zone", "_habit_zone", "_inset_m", "_point_in_no_go"}
WANT_CONST = {"SMOOTHING_REF_S", "SMOOTHING_MAX_STEP_S", "ZONE_SAMPLE_CENTER_WEIGHT", "ZONE_SAMPLE_ANGLES",
              "ZONE_AWAY_RESET_FRACTION", "ZONE_OUTVOTED_SHARE", "HABIT_CONFIDENT_SHARE", "TUNING_SPEC"}
ns = {"np": np, "math": math, "Point": Point, "shapely": shapely, "time": __import__("time"),
      "_FloorZones": type("_FZ", (), {}), "kpi": types.SimpleNamespace(NEIGHBOUR_REACH_M=1.5),
      "habits_mod": types.SimpleNamespace(learn=lambda *a, **k: None, gain_for=lambda *a, **k: 0.0),
      "runtime_mod": types.SimpleNamespace(DEFAULT_MAX_AGE_SECS=60.0), "_habits": {}, "_habits_last": {}, "_local_tz": None, "_zone_state": {}}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANT_FN:
        exec(compile(ast.Module([node], []), src_path, "exec"), ns)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(t, ast.Name) and t.id.isupper() for t in tgts):
            try:
                exec(compile(ast.Module([node], []), src_path, "exec"), ns)
            except Exception:
                pass
missing = (WANT_FN | WANT_CONST) - set(ns)
assert not missing, missing
# kpi's real reach, if it is a plain constant
for node in ast.parse(open(src_path.replace("__init__.py", "kpi.py")).read()).body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "NEIGHBOUR_REACH_M" for t in node.targets):
        ns["kpi"].NEIGHBOUR_REACH_M = ast.literal_eval(node.value)
SPEC = ns["TUNING_SPEC"]

lay = json.load(open(layout_path))["data"]
LIVE = lay.get("tuning") or {}
floors = {}
PROXY = {}
for f in lay["floor"]:
    polys = []
    for z in f.get("zones", []):
        c = z.get("cords") or []
        if len(c) < 3:
            continue
        p = Polygon([(q["x"], q["y"]) for q in c])
        if not p.is_valid:
            p = shapely.make_valid(p)
        polys.append((z["entity_id"], p, 0.0, bool(z.get("no_go"))))
    floors[f["name"]] = (polys, f.get("scale"))
    for rx in f.get("receivers", []):
        c = rx.get("cords") or {}
        if c.get("x") is not None:
            PROXY[rx.get("entity_id")] = Point(c["x"], c["y"])

rows = []
for fn in sorted(f for f in glob.glob(f"{log_dir}/*.jsonl*") if not f.endswith(".tmp")):
    for line in (gzip.open(fn, "rt") if fn.endswith(".gz") else open(fn)):
        r = json.loads(line)
        if r.get("cords") and r.get("floor") in floors and r.get("zone_raw"):
            rows.append(r)
rows.sort(key=lambda r: r["t"])


def run(tuning, sigma_k=0.5, anchor_fast=False):
    ns["_zone_state"].clear()
    layout = {"tuning": {**LIVE, **tuning}}
    ns["_tuning"] = lambda lay_, k: (lay_.get("tuning") or {}).get(k, SPEC[k][0]) if k in SPEC else (lay_.get("tuning") or {}).get(k, True)
    out = {}
    for r in rows:
        polys, scale = floors[r["floor"]]
        x, y = r["cords"]
        anchored = r.get("anchor") is not None
        kf = None
        if not anchored:
            sig = max(0.05, (r.get("rms_m") or 1.0) * sigma_k) * scale
            sp = (r.get("speed") or 0.0) * scale
            kf = {"floor": r["floor"], "P": np.diag([sig * sig, sig * sig, 1.0, 1.0]), "x": np.array([x, y, sp, 0.0])}
        # shortcut: hold (a floor challenge) is not in the log, so switches it would defer are allowed here.
        kw = {"anchor_point": PROXY.get(r["anchor"])} if anchor_fast and anchored else {}
        z, locked, _ = ns["_elect_zone"](r["ent"], r["floor"], r["zone_raw"], Point(x, y), kf, polys, scale, layout, now=r["t"], closed=set(r.get("closed") or ()), **kw)
        out.setdefault(r["ent"], []).append((r["t"], r["floor"], z))
    return out


def logged():
    out = {}
    for r in rows:
        out.setdefault(r["ent"], []).append((r["t"], r["floor"], r["zone"]))
    return out


def switches(series):
    """(entity, t, from, to) for each published room change (floor changes excluded)."""
    sw = []
    for e, s in series.items():
        for (t0, f0, z0), (t1, f1, z1) in zip(s, s[1:]):
            if f0 == f1 and z0 != z1 and z0 and z1:
                sw.append((e, t1, z0, z1))
    return sw


def bounces(sw, window=120):
    by = {}
    for e, t, a, b in sw:
        by.setdefault(e, []).append((t, a, b))
    n = 0
    for e, lst in by.items():
        for (t0, a0, b0), (t1, a1, b1) in zip(lst, lst[1:]):
            if b1 == a0 and a1 == b0 and t1 - t0 <= window:
                n += 1
    return n


def agree(a, b):
    same = tot = 0
    for e, s in a.items():
        for (t, f, z), (_t, _f, z2) in zip(s, b.get(e, [])):
            tot += 1
            same += z == z2
    return same / tot if tot else 0


def lead(sw, ref, window=90):
    """For each ref switch with a matching (same entity, same to-room) switch within the window,
    how many seconds earlier the candidate made it (positive = faster)."""
    by = {}
    for e, t, a, b in sw:
        by.setdefault((e, b), []).append(t)
    d = []
    for e, t, a, b in ref:
        cands = [t2 for t2 in by.get((e, b), []) if abs(t2 - t) <= window]
        if cands:
            d.append(t - min(cands, key=lambda t2: abs(t2 - t)))
    return d


hours = (rows[-1]["t"] - rows[0]["t"]) / 3600
print(f"{len(rows)} rows, {len({r['ent'] for r in rows})} things, {hours:.1f} h")
L = logged()
Lsw = switches(L)
print(f"logged: {len(Lsw)} switches, {bounces(Lsw)} bounces <=120s")
mode = sys.argv[4] if len(sys.argv) > 4 else "validate"
if mode == "validate":
    for k in (0.25, 0.5, 1.0):
        R = run({}, sigma_k=k)
        sw = switches(R)
        print(f"sigma_k {k}: agree {agree(R, L):.3f}  switches {len(sw)}  bounces {bounces(sw)}")
elif mode != "diag":
    k = float(mode)
    base = run({}, sigma_k=k)
    bsw = switches(base)
    print(f"replay base (smoothing {LIVE.get('zone_prob_smoothing', 0.6)}): {len(bsw)} switches, {bounces(bsw)} bounces, agree-with-log {agree(base, L):.3f}")
    variants = [("smoothing 0.4", {"zone_prob_smoothing": 0.4}, False),
                ("smoothing 0.3", {"zone_prob_smoothing": 0.3}, False),
                ("smoothing 0.4 + margin 0.2", {"zone_prob_smoothing": 0.4, "zone_switch_margin": 0.2}, False),
                ("smoothing 0.3 + margin 0.25", {"zone_prob_smoothing": 0.3, "zone_switch_margin": 0.25}, False),
                ("anchor fast (smoothing 0.6)", {}, True),
                ]
    variants = [v for v in variants if v[2]] if len(sys.argv) > 5 else variants
    for inset in ([float(x) for x in sys.argv[5].split(",")] if len(sys.argv) > 5 else [0.5]):
      LIVE["zone_anchor_inset_m"] = inset
      print("inset", inset)
      for name, tun, af in variants:
        R = run(tun, sigma_k=k, anchor_fast=af)
        sw = switches(R)
        d = lead(sw, bsw)
        q = statistics.quantiles(d, n=4) if len(d) > 3 else [0, 0, 0]
        fast = [x for x in d if x > 3]
        print(f"   switches made >3s sooner: {len(fast)}, median gain {statistics.median(fast) if fast else 0:.0f}s")
        print(f"{name:30s} switches {len(sw):4d} ({len(sw)-len(bsw):+d})  bounces {bounces(sw):3d} ({bounces(sw)-bounces(bsw):+d})  "
              f"matched {len(d)}/{len(bsw)}  faster by median {q[1]:.0f}s (p25 {q[0]:.0f}, p75 {q[2]:.0f})")

if mode == "diag":
    base = run({}, sigma_k=0.25); fast = run({}, sigma_k=0.25, anchor_fast=True)
    bsw, fsw = switches(base), switches(fast)
    anc = {(r["ent"], r["t"]): r.get("anchor") for r in rows}
    from collections import Counter
    def bl(sw):
        by = {}; out = []
        for e, t, a, b in sw: by.setdefault(e, []).append((t, a, b))
        for e, lst in by.items():
            for (t0, a0, b0), (t1, a1, b1) in zip(lst, lst[1:]):
                if b1 == a0 and a1 == b0 and t1 - t0 <= 120: out.append((e, t0, a0, b0, t1 - t0, anc.get((e, t0)), anc.get((e, t1))))
        return out
    bb = set((e, a, b) for e, t, a, b, *_ in bl(bsw))
    extra = bl(fsw)
    c = Counter((e, a, b, str(x)[:40], str(y)[:40]) for e, t, a, b, d, x, y in extra)
    for k, v in c.most_common(25): print(v, k)
    print("new switches by entity:", Counter(e for e, *_ in fsw).most_common(8), "vs", Counter(e for e, *_ in bsw).most_common(8))
