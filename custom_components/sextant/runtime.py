"""What a restart would otherwise throw away.

A cycle carries state that is not in the layout and not in any sensor: each
thing's Kalman filter, its room and spot elections with their smoothed
probabilities and timers, and when it arrived where it is. All of it is
built from the last few minutes of readings, so after a restart every thing
starts cold - rooms have to be re-earned, a spot cannot be held, and a
person follows whichever of their things happens to settle first. The house
did not change while Home Assistant was down; only Sextant's memory of it.

So the state is written to disk and read back if the gap was short. Read
back it is a starting point, never a lock: the elections carry on from
where they were and the next cycle of readings can disagree with them. A
longer gap keeps only when each thing was last heard and where, which is
what the Live page needs to say "away since 5:32 PM" instead of nothing.

Pure: the caller hands in the live dicts and gets plain JSON back.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# How long a gap still counts as "the house has not moved on": a restart, an
# update, a reboot. Past it the elections are stale and only the last sighting
# is kept.
DEFAULT_MAX_AGE_SECS = 300.0


# "There is no value here", as distinct from a value of None. A state dict is
# full of meaningful Nones - no challenger, not moving since, nothing pending -
# and dropping those keys hands the elections a dict they index by name and
# cannot read: the first st["still_since"] then throws the thing back to a cold
# start, which is the whole thing this module exists to avoid.
_DROP = object()


def _clean(value, depth=0):
    """JSON of a state dict: numbers, strings, bools, None, and lists of them.

    Anything else - a numpy array, an object, a NaN - is dropped rather than
    risk a store that cannot be written or read back.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else _DROP
    if depth >= 4:
        return _DROP
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            cleaned = _clean(v, depth + 1)
            if cleaned is not _DROP:
                out[str(k)] = cleaned
        return out
    if isinstance(value, (list, tuple)):
        return [None if (c := _clean(v, depth + 1)) is _DROP else c for v in value]
    if hasattr(value, "tolist"):          # numpy
        return _clean(value.tolist(), depth + 1)
    return _DROP


def _json(value):
    """``_clean`` for a caller that wants None rather than the sentinel."""
    cleaned = _clean(value)
    return None if cleaned is _DROP else cleaned


def _matrix(value, size):
    """``value`` as a size x size list of lists of finite floats, or None."""
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return None
    out = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != size:
            return None
        cleaned = [float(v) for v in row if isinstance(v, (int, float)) and math.isfinite(v)]
        if len(cleaned) != size:
            return None
        out.append(cleaned)
    return out


def _vector(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return None
    out = [float(v) for v in value if isinstance(v, (int, float)) and math.isfinite(v)]
    return out if len(out) == size else None


def snapshot(now, kf=None, zones=None, spots=None, arrivals=None, rows=None, floors=None, visits=None, wifi=None):
    """The state worth keeping, as JSON.

    ``rows`` are the published positions (ent, zone, sub_zone, floor, updated,
    cords): their last sighting is kept even when the rest is not.
    ``floors`` are the floor elections: {ent: {"name", "since", "probs"}}.
    Without them a restart elects every thing's floor from one cold cycle,
    and a floor that comes out differently discards the room and spot
    elections that were just restored - the floor change is what clears them.
    """
    things = {}

    def slot(entity):
        return things.setdefault(str(entity), {})

    for entity, state in (kf or {}).items():
        x, P = _json(state.get("x")), _json(state.get("P"))
        if _vector(x, 4) is None or _matrix(P, 4) is None:
            continue
        slot(entity)["kf"] = {"x": x, "P": P, "ts": state.get("ts"), "floor": state.get("floor")}
    for entity, state in (zones or {}).items():
        slot(entity)["zone"] = _json(state)
    for entity, state in (spots or {}).items():
        slot(entity)["spot"] = _json(state)
    for entity, state in (arrivals or {}).items():
        slot(entity)["arrived"] = _json(state)
    for entity, state in (floors or {}).items():
        slot(entity)["floor"] = _json(state)
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("ent"):
            continue
        cords = _json(row.get("cords"))
        slot(row["ent"])["last"] = {
            "zone": row.get("zone"), "spot": row.get("sub_zone"), "floor": row.get("floor"),
            "updated": row.get("updated"),
            "cords": cords if _vector(cords, 2) is not None else None,
        }
    out = {"saved_at": float(now), "things": things}
    # Each person's visit (persons.visit): when they arrived or left. Kept
    # whatever the gap, so a restart never turns "home since 07:40" into
    # "home since the restart".
    people = {str(p): _json(v) for p, v in (visits or {}).items() if isinstance(v, dict)}
    if people:
        out["people"] = people
    # What Wi-Fi association has taught (wifi.py): access-point footprints
    # and tracker-to-person scores. Kept whatever the gap: a week's learning
    # is worth more than a fresh start.
    if isinstance(wifi, dict) and (wifi.get("aps") or wifi.get("matches") or wifi.get("clients")):
        out["wifi"] = _json(wifi)
    return out


def _epoch(t):
    """A stored epoch second, or None: not a bool, finite, and within datetime's
    range. All inside the try: math.isfinite itself raises on an int too big
    for a float."""
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    try:
        f = float(t)
        if not math.isfinite(f) or f <= 0:
            return None
        datetime.fromtimestamp(f, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return f


def _counts(value):
    """A {name: finite non-negative number} table, or {} for anything else."""
    if not isinstance(value, dict):
        return {}
    return {str(k): float(v) for k, v in value.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0}


def _wifi_clean(wifi):
    """The Wi-Fi store (wifi.py) with only well-formed leaves: a footprint is
    two count tables, a match is finite agree/cycles (and a seen time). A
    stored record missing or mangling any of them is dropped, not carried
    into arithmetic that would raise every cycle."""
    aps, matches = {}, {}
    for mac, fp in (wifi.get("aps") or {}).items():
        if isinstance(fp, dict):
            floors = _counts(fp.get("floors"))
            if floors:
                aps[str(mac)] = {"floors": floors, "rooms": _counts(fp.get("rooms"))}
    for tracker, people in (wifi.get("matches") or {}).items():
        if not isinstance(people, dict):
            continue
        kept = {}
        for person, m in people.items():
            if not isinstance(m, dict):
                continue
            nums = _counts({"agree": m.get("agree"), "cycles": m.get("cycles")})
            if {"agree", "cycles"} <= set(nums) and nums["cycles"] > 0:
                rec = {"agree": nums["agree"], "cycles": nums["cycles"]}
                seen = _epoch(m.get("seen"))
                if seen is not None:
                    rec["seen"] = seen
                kept[str(person)] = rec
        if kept:
            matches[str(tracker)] = kept
    clients = {}
    raw_clients = wifi.get("clients")
    for entity, c in (raw_clients.items() if isinstance(raw_clients, dict) else ()):
        if isinstance(entity, str) and entity.startswith("device_tracker.") and isinstance(c, dict):
            mac = c.get("mac")
            clients[entity] = {"mac": str(mac).lower() if isinstance(mac, str) and mac else None}
    return {"aps": aps, "matches": matches, "clients": clients}


def restore(data, now, max_age=DEFAULT_MAX_AGE_SECS):
    """``{"kf", "zone", "spot", "arrivals", "floors", "last", "age"}`` from a snapshot.

    Everything comes back after a short gap; after a long one only ``last``,
    so the Live page can still say where a thing was and when. A snapshot
    from the future (the clock moved) is treated as a long gap.
    """
    out = {"kf": {}, "zone": {}, "spot": {}, "arrivals": {}, "floors": {}, "last": {}, "visits": {}, "wifi": None, "age": None}
    if not isinstance(data, dict):
        return out
    wifi = data.get("wifi")
    if isinstance(wifi, dict) and isinstance(wifi.get("aps"), dict) and isinstance(wifi.get("matches"), dict):
        out["wifi"] = _wifi_clean(wifi)
    people = data.get("people")
    if isinstance(people, dict):
        for person, v in people.items():
            if not isinstance(v, dict):
                continue
            arrived, departed = _epoch(v.get("arrived")), _epoch(v.get("departed"))
            # Exactly one of the two, as persons.visit writes them; anything else is noise.
            if (arrived is None) != (departed is None):
                kept = {"arrived": arrived, "departed": departed}
                if arrived is not None and v.get("via") in ("ble", "gps"):
                    kept["via"] = v["via"]
                out["visits"][person] = kept
    saved_at = data.get("saved_at")
    things = data.get("things")
    if not isinstance(saved_at, (int, float)) or not math.isfinite(saved_at) or not isinstance(things, dict):
        return out
    age = float(now) - float(saved_at)
    out["age"] = age
    fresh = 0 <= age <= max(0.0, float(max_age))
    for entity, state in things.items():
        if not isinstance(state, dict):
            continue
        last = state.get("last")
        if isinstance(last, dict) and isinstance(last.get("updated"), (int, float)):
            out["last"][entity] = last
        if not fresh:
            continue
        kf = state.get("kf")
        if isinstance(kf, dict):
            x, P = _vector(kf.get("x"), 4), _matrix(kf.get("P"), 4)
            ts, floor = kf.get("ts"), kf.get("floor")
            if x and P and isinstance(ts, (int, float)) and isinstance(floor, str):
                out["kf"][entity] = {"x": x, "P": P, "ts": float(ts), "floor": floor}
        for key, target in (("zone", "zone"), ("spot", "spot"), ("arrived", "arrivals"),
                            ("floor", "floors")):
            value = state.get(key)
            if isinstance(value, dict) and value:
                out[target][entity] = value
    return out
