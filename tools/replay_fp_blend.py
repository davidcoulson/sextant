"""Replay every truth mark's samples under different fingerprint blend rules.

The live evaluator (sextant/truth/evaluate) can only sweep the blend weight. This
re-solves each stored sample once geometrically and once by fingerprint, with the
integration's own code, then scores any rule for mixing the two against the mark.

Inputs (all captured from a running house):
  layout.json   the layout as sextant/layout/get returns it
  truth.json    /config/.storage/sextant_truth
  gains.json    /config/.storage/sextant_fingerprint_gains
  rang*.json    one or more proxy-to-proxy captures: {tx: {rx: [distance_raw, distance, stamp, rssi]}}
                (bermuda.dump_devices for the proxies' own addresses, adverts reduced to that)

usage: uv run --no-project --with-requirements requirements_test.txt python tools/replay_fp_blend.py \
           layout.json truth.json gains.json rang0.json [rang1.json ...] [--entity SLUG] [--per-mark]

shortcut: rooms are the layout's polygons as drawn (legacy four-corner rectangles are not
re-ordered), every mark is scored at the same weights (per-thing weights are ignored), and
the capture's newest advert stands in for "now" when ageing readings out; use the live
evaluator when those matter.
"""
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "custom_components"), str(ROOT / "tests")]
import conftest  # noqa: E402,F401  the tests' Home Assistant stand-ins, so the backend imports without HA
import sextant as core  # noqa: E402
from sextant import fingerprint, truth as truth_mod  # noqa: E402
from shapely.geometry import Point, Polygon  # noqa: E402

REF_MAX_AGE = fingerprint.REF_MAX_AGE_SECS

# name -> share of the fingerprint in the fix, from the tuned weight, the match's
# scale trust and its confidence. "now" is what _fuse_fingerprint does today.
RULES = {
    "now": lambda w, trust, conf: w * trust,
    "x conf": lambda w, trust, conf: w * trust * conf,
    "x min(1, 2conf)": lambda w, trust, conf: w * trust * min(1.0, 2 * conf),
    "x min(1, 3conf)": lambda w, trust, conf: w * trust * min(1.0, 3 * conf),
    "off below 0.25": lambda w, trust, conf: w * trust * (conf >= 0.25),
    "off below 0.35": lambda w, trust, conf: w * trust * (conf >= 0.35),
}
WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)


def load_vectors(paths):
    """{tx: {rx: median raw metres}} over the captures, as ReferenceDB.vectors() builds it."""
    samples = {}
    for path in paths:
        cap = json.load(open(path))
        now = max((a[2] for heard in cap.values() for a in heard.values() if a[2] is not None), default=0.0)
        for tx, heard in cap.items():
            for rx, (raw, filtered, stamp, _rssi) in heard.items():
                d = raw if raw is not None else filtered
                if rx == tx or d is None or not math.isfinite(d) or d < core.INVALID_RANGE_M:
                    continue
                if stamp is not None and now - stamp > REF_MAX_AGE:
                    continue
                samples.setdefault((tx.lower(), rx.lower()), []).append(float(d))
    out = {}
    for (tx, rx), ds in samples.items():
        out.setdefault(tx, {})[rx] = statistics.median(ds)
    return out


def room_lookup(layout, floor_name):
    floor = next(f for f in layout["floor"] if f["name"] == floor_name)
    polys = []
    for z in floor.get("zones") or []:
        pts = [(p["x"], p["y"]) for p in z.get("cords") or []]
        if len(pts) >= 3 and not z.get("no_go"):
            polys.append((z.get("entity_id"), Polygon(pts).buffer(0)))
    return lambda pt: next((zid for zid, poly in polys if poly.covers(Point(pt))), None)


def solve_mark(layout, mark, vectors, gains):
    """Per usable sample: (geo fix or None, fingerprint match or None, whether the match may
    stand alone), or None when the floor has no references to match against."""
    entity, floor = mark["entity"], mark["floor"]
    gain = core._tuning(layout, "fingerprint_ref_gain")
    if core._tuning(layout, "fingerprint_auto_gain"):
        gain *= gains.get("learned_gain", 1.0) * (gains.get("thing_gain") or {}).get(entity, 1.0)
    # A mark must not match its own reference (as the live evaluator does).
    extra = [r for r in core._mark_refs(layout, entity) or [] if r.get("slug") != f"mark:{mark['id']}"]
    refs = fingerprint.build_references(layout, vectors, gain, extra=extra or None).get(floor)
    if not refs:
        return None
    k, missing = core._tuning(layout, "fingerprint_k"), core._tuning(layout, "fingerprint_missing_m")
    out = []
    for s in core._rebased_samples(layout, mark):
        fj = (s.get("floors") or {}).get(floor)
        if not fj:
            continue
        geo = core._solve_floor_jobs([{
            "floor": floor, "weighted": [tuple(pt) for pt in fj["weighted"]],
            "bounds": None if fj.get("bounds") is None else tuple(fj["bounds"]),
            "min_wr": fj["min_wr"], "stable_hint": None, "scale": fj["scale"], "zone_polys": [], "fingerprint": None,
        }])[0]
        m = fingerprint.match(s["thing_vec"], refs, k=k, missing_m=missing) if s.get("thing_vec") else None
        # As _solve_floor_jobs: a match with no geometry behind it must sit near the nearest proxy.
        alone = False
        if m and fj["weighted"] and fj["scale"]:
            x, y, r = min(fj["weighted"], key=lambda pt: pt[2])[:3]
            alone = math.hypot(m["x"] - x, m["y"] - y) <= r + core.FP_ONLY_MAX_NEAREST_M * fj["scale"]
        out.append((None if geo is None else geo[0], m, alone))
    return out


def blend(geo, m, alone, name, w0, rule):
    """The fix one rule gives. The ends of the sweep are the live modes: weight 0 never
    matches, and today's rule at weight 1 is the match itself (fingerprint mode)."""
    if w0 == 0 or m is None:
        return geo
    if geo is None:
        return (m["x"], m["y"]) if alone and rule(w0, 1.0, m["conf"]) > 0 else None
    if name == "now" and w0 == 1:
        return (m["x"], m["y"])
    w = rule(w0, fingerprint.trust(m.get("ratio")), m["conf"])
    return ((1 - w) * geo[0] + w * m["x"], (1 - w) * geo[1] + w * m["y"])


def score(solved, mark, scale, zone_of, col):
    """(mean error m, share in the mark's room) or None."""
    want = zone_of((mark["x"], mark["y"]))
    errs, right = [], 0
    for geo, m, alone in solved:
        fix = blend(geo, m, alone, *col)
        if fix is None:
            continue
        errs.append(math.hypot(fix[0] - mark["x"], fix[1] - mark["y"]) / scale)
        right += want is not None and zone_of(fix) == want
    return (statistics.fmean(errs), right / len(errs)) if errs else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("layout"), ap.add_argument("truth"), ap.add_argument("gains"), ap.add_argument("ranging", nargs="+")
    ap.add_argument("--entity", help="only this thing's marks")
    ap.add_argument("--per-mark", action="store_true", help="also print each mark at the tuned weight")
    args = ap.parse_args()
    layout = json.load(open(args.layout))
    layout = layout.get("layout", layout)
    marks = json.load(open(args.truth))["data"]["marks"]
    gains = json.load(open(args.gains))["data"]
    vectors = load_vectors(args.ranging)
    core._set_truth_marks(marks)
    tuned = core._tuning(layout, "fingerprint_weight")
    print(f"{len(marks)} marks, {sum(len(v) for v in vectors.values())} proxy pairs, tuned weight {tuned}")

    cols = [(f"{name} w={w}", (name, w, fn)) for name, fn in RULES.items() for w in sorted({*WEIGHTS, tuned})
            if name == "now" or w in (tuned, 1.0)]
    no_refs = 0
    groups = {}   # group -> column -> [(err, ok)]
    for mark in marks:
        if args.entity and mark["entity"] != args.entity:
            continue
        floor = next((f for f in layout["floor"] if f["name"] == mark["floor"]), None)
        if not floor or not floor.get("scale"):
            continue
        solved = solve_mark(layout, mark, vectors, gains)
        if solved is None:
            no_refs += 1
            continue
        if len(solved) < truth_mod.MIN_SAMPLES:
            continue
        zone_of = room_lookup(layout, mark["floor"])
        row = {name: score(solved, mark, floor["scale"], zone_of, col) for name, col in cols}
        if any(v is None for v in row.values()):
            continue
        if args.per_mark:
            confs = [m["conf"] for _g, m, _a in solved if m]
            print(f"  mark {mark['id']:>3} {mark['entity'][-26:]:26} {mark['floor'][:8]:8} conf {statistics.fmean(confs) if confs else 0:.2f}  "
                  + "  ".join(f"{n.split(' w=')[0]}: {row[n][0]:.2f}m {row[n][1]:.0%}" for n, _ in cols if n.endswith(f"w={tuned}")))
        phone = any(t in mark["entity"] for t in ("phone", "watch"))
        for g in ("all", f"floor {mark['floor']}", "phones+watches" if phone else "everything else"):
            for name, v in row.items():
                groups.setdefault(g, {}).setdefault(name, []).append(v)
    if no_refs:
        print(f"{no_refs} marks skipped: no references on their floor")
    for g, by_col in groups.items():
        n = len(next(iter(by_col.values())))
        print(f"\n{g} ({n} marks): mean error m / share in the right room")
        for name, vals in by_col.items():
            print(f"  {name:24} {statistics.fmean(v[0] for v in vals):5.2f}  {statistics.fmean(v[1] for v in vals):5.1%}")


if __name__ == "__main__":
    main()
