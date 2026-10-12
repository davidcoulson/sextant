"""mmWave radars on the plan: their targets as points, and which thing is which.

An LD2450-type radar (Everything Presence Pro and Lite, Apollo R PRO-1) tracks
up to three people and reports each as x/y in its own frame: y straight out
from the sensor, x across it. Placed on the plan with the direction it faces,
each target becomes a point on the floor, to a few tens of centimetres - far
better than Bluetooth ranging manages. Sextant uses them three ways:

- a thing whose Bluetooth fix is near a target is placed on the target;
- one target and one thing, both still, is a location pin nobody had to tap;
- a target no thing claims is a person Sextant has no device for.

Two radars that see the same person report a target each; within
MERGE_RADIUS_M of each other they are one person (``merge``).

A radar is on the wall (the default) or on the ceiling. A 2D one on the
wall, the LD2450, ranges in a straight line to the chest, so its x/y need
the mounting height to become floor distance. A 3D radar (the LD6004) and
any radar on the ceiling report x/y across the floor already; a 3D radar's
z then gives how high the target is, and from that a rough posture.

This module holds the geometry and the pairing; it imports nothing from the
rest of the package, so all of it is testable without Home Assistant.
"""
import math
import re

# The LD2450's field of view is ±60 degrees; its range is set on the device.
FOV_DEG = 120.0
DEFAULT_RANGE_M = 6.0
# A target this close to the sensor on both axes is the radar's "no target".
NO_TARGET_M = 0.05
# What the radar ranges to on a person: the chest, about a metre up standing
# (a little less sitting). A sensor mounted higher measures the slant to it.
TARGET_HEIGHT_M = 1.0
# Two radars' targets this close are one person (each radar sees each
# person once, so two targets of one radar are always two people).
MERGE_RADIUS_M = 0.8
# How high a 3D radar's target is, by posture: the radar tracks the middle
# of the body, so lying is below half a metre and sitting below about 1.1 m.
POSTURE_LYING_M = 0.5
POSTURE_SITTING_M = 1.1
MOUNTS = ("wall", "ceiling")
# How a 3D radar's z reads: height above the floor, or up / down from the
# sensor (firmwares differ; the Edit page shows the heights to check it).
Z_REFS = ("floor", "up", "down")

_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048, "yd": 0.9144}


def to_metres(value, unit):
    """A reading in metres, or None when it is not a number in a length unit."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    factor = _TO_M.get(str(unit or "mm").strip().lower())
    return None if factor is None else v * factor


_TARGET = re.compile(r"target_?(\d{1,2})_(x|y|z|speed|active)$")
_RANGE = re.compile(r"(tracking_detection_range|max_distance|detection_range)$")
_ANGLE = re.compile(r"(installation_angle|tracking_sensor_angle)$")


def device_spec(entity_ids):
    """A radar's entities, from the entity ids of one device.

    Returns {"targets": [{"x", "y", "z", "speed", "active"} per target that
    has both x and y], "has_z", "range_entity", "angle_entity"}, or None when
    the device reports no target coordinates (a plain presence sensor).
    """
    targets = {}
    range_entity = angle_entity = None
    for eid in sorted(entity_ids):
        obj = eid.split(".", 1)[-1]
        m = _TARGET.search(obj)
        if m:
            domain = eid.split(".", 1)[0]
            if m.group(2) == "active" and domain != "binary_sensor":
                continue
            targets.setdefault(int(m.group(1)), {})[m.group(2)] = eid
        elif eid.startswith("number.") and _RANGE.search(obj):
            range_entity = range_entity or eid
        elif eid.startswith("number.") and _ANGLE.search(obj):
            angle_entity = angle_entity or eid
    usable = [
        {"x": t["x"], "y": t["y"], "z": t.get("z"), "speed": t.get("speed"), "active": t.get("active")}
        for _n, t in sorted(targets.items()) if "x" in t and "y" in t
    ]
    if not usable:
        return None
    return {"targets": usable, "has_z": any(t["z"] for t in usable),
            "range_entity": range_entity, "angle_entity": angle_entity}


def radar_range_m(spec, get_state):
    """The radar's configured range, in metres (the chip's own 6 m when unset)."""
    st = get_state(spec.get("range_entity")) if spec.get("range_entity") else None
    if st is not None:
        r = to_metres(st.state, st.attributes.get("unit_of_measurement"))
        if r and 0.5 <= r <= 20:
            return r
    return DEFAULT_RANGE_M


def read_targets(spec, get_state, range_m=None):
    """The radar's current targets in its own frame:
    [(index, x_m, y_m, speed_ms, z_m)], z_m None unless the radar reports it.

    A target counts when both coordinates are numbers, it is not at the
    origin (the radar's "none"), it is within range, and - where the device
    says - it is active.
    """
    rng = range_m if range_m is not None else radar_range_m(spec, get_state)
    out = []
    for i, t in enumerate(spec.get("targets") or [], start=1):
        if t.get("active"):
            act = get_state(t["active"])
            if act is None or act.state != "on":
                continue
        xs, ys = get_state(t["x"]), get_state(t["y"])
        if xs is None or ys is None:
            continue
        x = to_metres(xs.state, xs.attributes.get("unit_of_measurement"))
        y = to_metres(ys.state, ys.attributes.get("unit_of_measurement"))
        if x is None or y is None or (abs(x) < NO_TARGET_M and abs(y) < NO_TARGET_M):
            continue
        if math.hypot(x, y) > rng + 0.5:
            continue
        speed = None
        if t.get("speed"):
            ss = get_state(t["speed"])
            if ss is not None:
                unit = str(ss.attributes.get("unit_of_measurement") or "").lower()
                per = {"mm/s": 0.001, "cm/s": 0.01, "m/s": 1.0, "in/s": 0.0254, "mph": 0.44704, "km/h": 1 / 3.6}.get(unit)
                try:
                    speed = abs(float(ss.state)) * per if per else None
                except (TypeError, ValueError):
                    speed = None
        z = None
        if t.get("z"):
            zs = get_state(t["z"])
            if zs is not None:
                z = to_metres(zs.state, zs.attributes.get("unit_of_measurement"))
        out.append((i, x, y, speed, z))
    return out


def floor_factor(x_m, y_m, height_m):
    """What turns a target's reported x/y into distances across the floor.

    The radar ranges in a straight line from where it is mounted to the
    person's chest (TARGET_HEIGHT_M), and keeps the angle; the floor distance
    is the slant range less that height difference, at the same angle. From
    2 m up, someone 3 m out reads 3.16 m (5 % long), someone 1 m out reads
    1.41 m (40 % long). Unset or no higher than a chest: no correction.
    """
    try:
        dh = float(height_m) - TARGET_HEIGHT_M
    except (TypeError, ValueError):
        return 1.0
    r = math.hypot(x_m, y_m)
    if dh <= 0 or r <= 0:
        return 1.0
    return math.sqrt(max(r * r - dh * dh, 0.0)) / r


def floor_range_m(range_m, height_m):
    """How far across the floor a slant range reaches (see floor_factor)."""
    return range_m * floor_factor(0.0, range_m, height_m)


def mount(radar):
    """Where the radar is mounted: "wall" (the default) or "ceiling"."""
    return "ceiling" if radar.get("mount") == "ceiling" else "wall"


def slant_corrected(radar, z_m=None):
    """Whether the radar's x/y are a slant to correct by the mounting height:
    only a 2D radar on the wall. A 3D radar's x/y are across the floor (its z
    is the height), and on the ceiling x/y are offsets from the point below."""
    return mount(radar) == "wall" and z_m is None


def target_height_m(radar, z_m):
    """How high a 3D radar's target is above the floor, or None.

    ``z_ref`` says how the radar reads z: "floor" (height above the floor),
    "up" (up from the sensor) or "down" (down from it). Unset: down on the
    ceiling, up on the wall. Measured from the sensor, the mounting height
    must be set."""
    if z_m is None:
        return None
    ref = radar.get("z_ref") if radar.get("z_ref") in Z_REFS else ("down" if mount(radar) == "ceiling" else "up")
    if ref == "floor":
        return z_m
    try:
        h = float(radar.get("height_m"))
    except (TypeError, ValueError):
        return None
    return h - abs(z_m) if ref == "down" else h + z_m


def posture(height_m):
    """"lying", "sitting" or "standing" from a target's height, or None."""
    if height_m is None:
        return None
    return "lying" if height_m < POSTURE_LYING_M else "sitting" if height_m < POSTURE_SITTING_M else "standing"


def floor_reach_m(radar, range_m, fov_deg=FOV_DEG):
    """How far from the point below it the radar covers, across the floor.

    On the wall: the range, less the slant (floor_range_m). On the ceiling:
    a circle - the cone of the field of view at chest height, and no further
    than the range reaches down to it."""
    if mount(radar) == "wall":
        return floor_range_m(range_m, radar.get("height_m"))
    try:
        dh = float(radar.get("height_m")) - TARGET_HEIGHT_M
    except (TypeError, ValueError):
        return range_m
    if dh <= 0:
        return range_m
    cone = dh * math.tan(math.radians(fov_deg / 2))
    return min(cone, math.sqrt(max(range_m * range_m - dh * dh, 0.0)))


def to_plan(radar, x_m, y_m, px_per_m, z_m=None):
    """A target in the radar's frame, on the plan (pixels).

    ``radar`` is the layout's radar: {"cords": {x, y}, "heading": degrees
    clockwise from straight up the plan, "flip": bool, "mount"}. The target
    is y metres along the heading and x across it, to the right of the
    heading unless ``flip`` (sensors disagree on which side is positive x).
    On the ceiling the heading is the way the sensor's y axis points. For a
    2D radar on the wall, the mounting ``height_m`` turns the slant it
    reports into floor distance (floor_factor).
    """
    k = floor_factor(x_m, y_m, radar.get("height_m")) if slant_corrected(radar, z_m) else 1.0
    x_m, y_m = x_m * k, y_m * k
    h = math.radians(float(radar.get("heading") or 0.0))
    fwd = (math.sin(h), -math.cos(h))
    right = (math.cos(h), math.sin(h))
    side = -1.0 if radar.get("flip") else 1.0
    cx, cy = float(radar["cords"]["x"]), float(radar["cords"]["y"])
    return (cx + px_per_m * (y_m * fwd[0] + side * x_m * right[0]),
            cy + px_per_m * (y_m * fwd[1] + side * x_m * right[1]))


def merge(targets, radius):
    """Which targets are the same person, seen by more than one radar.

    ``targets`` is [(key, radar, (x, y))]. Returns a list of clusters, each
    a list of keys: two clusters join while their centres are within
    ``radius`` and no radar is in both (a radar sees each person once).
    Closest pair first, so a person between two others joins the nearer."""
    clusters = [{"keys": [k], "radars": {r}, "pts": [p]} for k, r, p in targets]

    def centre(c):
        return (sum(p[0] for p in c["pts"]) / len(c["pts"]), sum(p[1] for p in c["pts"]) / len(c["pts"]))

    while True:
        best = None
        for i in range(len(clusters)):
            ci = centre(clusters[i])
            for j in range(i + 1, len(clusters)):
                if clusters[i]["radars"] & clusters[j]["radars"]:
                    continue
                cj = centre(clusters[j])
                d = math.hypot(ci[0] - cj[0], ci[1] - cj[1])
                if d <= radius and (best is None or d < best[0]):
                    best = (d, i, j)
        if best is None:
            return [c["keys"] for c in clusters]
        _d, i, j = best
        a, b = clusters[i], clusters.pop(j)
        a["keys"] += b["keys"]
        a["radars"] |= b["radars"]
        a["pts"] += b["pts"]


def pair(targets, things, radius):
    """One-to-one pairs of targets and things, nearest first, within ``radius``.

    ``targets`` is [(key, (x, y))], ``things`` [(key, (x, y))], both in the
    same units as ``radius``. Returns ({target key: thing key}, [unpaired
    target keys]). Greedy on distance, which for a handful of each is the
    same answer the optimal assignment gives in all but contrived layouts.
    """
    cand = sorted(
        (math.hypot(tp[0] - hp[0], tp[1] - hp[1]), tk, hk)
        for tk, tp in targets for hk, hp in things
    )
    by_target, used = {}, set()
    for d, tk, hk in cand:
        if d > radius:
            break
        if tk in by_target or hk in used:
            continue
        by_target[tk] = hk
        used.add(hk)
    return by_target, [tk for tk, _p in targets if tk not in by_target]
