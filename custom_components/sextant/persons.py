"""Where a person is, from the things they own.

A thing can name its owner, a Home Assistant person (thing_owners in the
layout). A person's location is then one of their things' locations, and the
question is which one speaks for them. The phone left on the couch for an
hour does not; the watch that just crossed the room does. So:

1. Only things heard recently (within stale_after_secs) and placed in a room.
2. A thing that arrived where it is within RECENT_MOVE_SECS beats one that
   has sat there longer - it is being carried. Arrival is metres moved
   (settled_since), not the tracker's own "moving" flag: a watch on its
   nightstand whose fix alternates between two points reads as moving. Among those,
   what is usually on a body wins: a pet's own tag, a watch, a phone.
   A watch that says it is worn and unlocked beats all of this, and one that
   says it is locked takes no part (watch_adverts.worn_now); the rules here
   and below guess only for a watch whose lock state is unknown.
3. When nothing is on the move, the thing that arrived where it is most
   recently wins: the phone that came downstairs this morning, not the
   watch that has sat on its charger since last night. Class does not
   decide here - it did at first, and the watch on the nightstand won.

Only things that give their owner's location take part (locates_owner): by
class a watch, a phone or a person's or pet's own tag; headphones, keys, a
bag only when the thing is switched on for it.
4. Then whichever moved most recently.

Pure: the caller hands in each thing's latest published row.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .const import FIT_ATTRIBUTES
from .rooms import PET_CLASSES

# A thing still for longer than this is probably not being carried.
RECENT_MOVE_SECS = 600.0
# "Where it is" for arrival purposes: within this many metres of its place.
# Measured in metres, not by room or spot name - a watch on a nightstand at
# the edge of its spot flips between the spot and the room with every
# wobble, and every flip looked like a fresh arrival.
STAY_RADIUS_M = 2.0
# Somewhere else for less than this is noise, not a move: a stray fix, or the
# minute after a restart when a watch on its nightstand was placed a floor
# down three times running.
MOVE_CONFIRM_SECS = 120.0
# Unheard for longer than this, and the stay is over even when it comes back
# to the same place: it left (the default away_after_secs). A restart's
# silence, a minute or two, is far shorter and passes over as before.
ABSENCE_ENDS_STAY_SECS = 900.0
# The history's "dropout" mark (history.GAP_DROPOUT): nothing was heard
# between this point and the one before it.
GAP_DROPOUT = 2
# Higher speaks for its owner first, among things equally recently moved.
CARRY_PRIORITY = {"cat": 4, "dog": 4, "paw": 4, "watch": 3, "phone": 2, "headphones": 1}
# Classes whose place is their owner's place, unless the thing says otherwise
# (thing_locates_owner). Headphones, keys, a bag go with you some of the time;
# where they are is not where you are. A purse and a backpack are no different:
# they are in the hall far more of the day than they are on a shoulder.
LOCATES_BY_DEFAULT = {"watch", "phone", "person", "man", "woman", "child", "cat", "dog", "paw"}
# The sensors each person gets: (suffix, label).
PERSON_SENSOR_KINDS = [
    ("sextant_person_location", "Location"),
    ("sextant_person_room", "Room"),
    ("sextant_person_floor", "Floor"),
    ("sextant_person_sleep", "Slept In"),
]
SLEEP_MAX_STEP_S = 300.0   # a longer gap between cycles (a restart) counts no more than this


def sleep_tally(tally, place, now, tz, start_h, end_h):
    """The night's time in each room, for the "slept in" sensor.

    ``tally`` is ``{"night", "rooms": {"Room (Floor)": secs}, "places": {key: [room, floor]}, "place", "at"}``
    or None; ``place`` is (room, floor) or None (out, no room). Each interval counts for the place
    seen at its start. The night is the local ``start_h`` to ``end_h`` window (equal hours: off),
    named for the date it starts on. Outside the window the last night's tally stands; the first
    cycle of a new night starts a fresh one.
    """
    from datetime import datetime, timedelta  # noqa: PLC0415
    lt = datetime.fromtimestamp(now, tz)
    h = lt.hour + lt.minute / 60.0
    inside = (start_h <= h < end_h) if start_h < end_h else (h >= start_h or h < end_h) if start_h > end_h else False
    night = ((lt - timedelta(days=1)) if start_h > end_h and h < end_h else lt).date().isoformat()
    if inside and (not tally or tally.get("night") != night):
        tally = {"night": night, "rooms": {}, "places": {}, "place": None, "at": None}
    if not tally:
        return tally
    rooms, places = dict(tally["rooms"]), dict(tally["places"])
    prev = tally.get("place")
    if prev and tally.get("at"):
        key = f"{prev[0]} ({prev[1]})"
        rooms[key] = rooms.get(key, 0.0) + min(max(0.0, now - tally["at"]), SLEEP_MAX_STEP_S)
        places[key] = list(prev)
    if not inside:
        return {**tally, "rooms": rooms, "places": places, "place": None, "at": None}
    return {"night": night, "rooms": rooms, "places": places, "place": list(place) if place else None, "at": now}


def sleep_state(tally):
    """(state, attributes) for the "slept in" sensor: the room with the most of the night."""
    tally = tally or {}
    rooms, tonight = tally.get("rooms") or {}, tally.get("at") is not None
    if not rooms:
        return "unknown", {"night": tally.get("night"), "floor": None, "tonight": tonight, "minutes": {}}
    key = max(rooms, key=rooms.get)
    room, floor = tally["places"][key]
    return room, {"night": tally["night"], "floor": floor, "tonight": tonight,
                  "minutes": {k: round(v / 60.0) for k, v in sorted(rooms.items(), key=lambda kv: -kv[1])}}


def owners(layout) -> dict[str, list[str]]:
    """person entity id -> the things it owns.

    A person with GPS trackers but no thing is here too, owning nothing: GPS
    alone places them (and gives them arrival and departure events).
    """
    out: dict[str, list[str]] = {}
    raw = layout.get("thing_owners") if isinstance(layout, dict) else None
    for thing, person in (raw or {}).items():
        if isinstance(person, str) and person.startswith("person."):
            out.setdefault(person, []).append(thing)
    gps = layout.get("person_trackers") if isinstance(layout, dict) else None
    for person, trackers in (gps or {}).items() if isinstance(gps, dict) else ():
        if isinstance(person, str) and person.startswith("person.") and trackers:
            out.setdefault(person, [])
    return out


def pet_persons(by_person, classes) -> set[str]:
    """The persons that are pets: everything they own is a cat, dog or paw tag.

    Home Assistant lets a cat be a person.* entity; Sextant tells them apart by
    what they carry.
    """
    return {p for p, things in by_person.items() if things and all(classes.get(t) in PET_CLASSES for t in things)}


def sensor_entity_id(slug, suffix, is_pet) -> str:
    """sensor.<slug>_sextant_person_location, or ..._sextant_pet_location for a pet."""
    return f"sensor.{slug}_" + (suffix.replace("sextant_person_", "sextant_pet_", 1) if is_pet else suffix)


def device_model(is_pet) -> str:
    """The model on a person's (or pet's) Sextant device."""
    return "Pet" if is_pet else "Person"


def locates_owner(layout, ent, cls) -> bool:
    """Whether this thing's place may stand for its owner's: its own setting, else its class."""
    own = (layout.get("thing_locates_owner") or {}).get(ent) if isinstance(layout, dict) else None
    if isinstance(own, bool):
        return own
    return cls in LOCATES_BY_DEFAULT


def always_home(layout, ent, cls) -> bool:
    """Whether a day of silence from this thing means something is wrong (the
    dead-thing repair): its own setting (thing_always_home), else its class's
    (class_always_home), else the default - a pet's tag never leaves for
    long, where a phone or a suitcase is away for days."""
    layout = layout if isinstance(layout, dict) else {}
    for key, who in (("thing_always_home", ent), ("class_always_home", cls)):
        table = layout.get(key)
        own = table.get(who) if isinstance(table, dict) else None
        if isinstance(own, bool):
            return own
    return cls in PET_CLASSES


# What a battery sensor says when its device is on a charger: iCloud3 reports
# Charging / Charged / Full, Apple's Find My "Charged" at 100 %, the companion
# app Charging / Full. "Not Charging" and "NotCharging" are off the charger.
CHARGER_STATES = {"charging", "charged", "full", "on"}


def on_charger(state) -> bool:
    """Whether a battery (or charging binary) sensor's state says it is on a charger.

    Anything unreadable - unavailable, unknown, no sensor - is False: a sensor
    that has nothing to say must not take a thing out of the running.
    """
    return isinstance(state, str) and state.strip().lower() in CHARGER_STATES


def charging_now(state) -> bool:
    """Whether the sensor says it is drawing power right now. "Charged" and "Full"
    do not: a source that refreshes rarely (iCloud3, Find My) goes on saying
    "Charged" for hours after the watch is back on a wrist."""
    return isinstance(state, str) and state.strip().lower() in {"charging", "on"}


def last_charge_began(states):
    """When a charger sensor's last charge began, from its recorded states (oldest
    first, each with ``state`` and ``last_changed``); None if never. The START of
    the last run of charging states: "Charging" then "Full" is one charge."""
    began = None
    for st in reversed(list(states or [])):
        changed = getattr(st, "last_changed", None)
        if on_charger(getattr(st, "state", None)) and changed is not None:
            began = changed.timestamp()
        elif began is not None:
            break
    return began


def still_on_charger(charging: bool, arrived, last_charging, since: float, full: bool = False):
    """(on the charger, when it last began charging).

    A watch that reaches its charge limit reads "NotCharging" while it still
    sits on the puck. So once seen charging, a thing stays on its charger
    until it moves: until it arrived where it is after that charge began.
    ``since`` is when the sensor's reading began, not now: a reading that
    lags a watch already carried off must not hold it where it lands.
    ``full`` is a "Charged"/"Full" reading: it was on a charger, and like
    "NotCharging" it holds only until the thing moves.
    """
    if charging:
        return True, since
    if full:
        # The full reading is itself a charge, from when it began: one finished while
        # nobody watched (a restart, a sensor that skips "Charging") must still hold.
        # shortcut: a late "Charged" can hold a watch already carried off until its next move; use the recorded charge start if that bites
        last_charging = max(last_charging or 0, since)
    held = (isinstance(last_charging, (int, float)) and isinstance(arrived, (int, float))
            and arrived <= last_charging)
    return held, last_charging


def settled_since(points, here, radius=STAY_RADIUS_M, confirm_secs=MOVE_CONFIRM_SECS,
                  absence_secs=ABSENCE_ENDS_STAY_SECS):
    """When a thing arrived within ``radius`` metres of ``here``, from its history.

    ``points``: (t, floor, x_m, y_m) or (t, floor, x_m, y_m, gap), oldest
    first; ``here``: (floor, x_m, y_m). Walks back from the newest point
    until the thing had been elsewhere (another floor, or farther than
    ``radius``) for ``confirm_secs``, or went unheard for ``absence_secs``
    (a point whose gap is GAP_DROPOUT, after that long a silence); returns
    the time of the first point of the stay that followed, or None with no
    history here. Shorter absences are passed over as noise.
    """
    floor, hx, hy = here
    since = None
    newer = None   # (t, gap) of the point after this one
    for p in reversed(points):
        t, f, x, y = p[:4]
        if (since is not None and newer is not None and newer[1] == GAP_DROPOUT
                and newer[0] - t >= absence_secs):
            break
        if f == floor and x is not None and y is not None and math.hypot(x - hx, y - hy) <= radius:
            since = t
        elif since is not None and since - t >= confirm_secs:
            break
        newer = (t, p[4] if len(p) > 4 else 0)
    return since


def pick(things, now: float, stale_after: float, watch_still: float = 14400.0):
    """The thing that speaks for its owner now, or None.

    ``things`` are dicts: ent, cls, updated (epoch s),
    arrived (epoch s: when it came within STAY_RADIUS_M of where it is now),
    zone, sub_zone, floor, and for a watch worn (True: on a wrist and unlocked,
    False: locked, None: unknown). ``watch_still`` is the watch_still_secs tuning.
    """
    fresh = [
        t for t in things
        if isinstance(t.get("updated"), (int, float)) and now - t["updated"] <= stale_after
        and t.get("zone") not in (None, "", "unknown")
        # A watch that says it is locked is on nobody's wrist; one that says it is worn
        # and unlocked is, whatever its charger sensor last said.
        and t.get("worn") is not False
        and (t.get("worn") or not t.get("on_charger"))   # a watch on its charger is not on anybody's wrist
    ]
    if not fresh:
        return None

    def key(t):
        arrived = t.get("arrived")
        age = max(0.0, now - arrived) if isinstance(arrived, (int, float)) else float("inf")
        recent = age <= RECENT_MOVE_SECS
        return (not recent, -CARRY_PRIORITY.get(t.get("cls"), 0) if recent else 0, age)

    # A watch worn and unlocked is on its owner (watch_adverts.worn_now): it speaks for them.
    if worn := [t for t in fresh if t.get("worn")]:
        return min(worn, key=key)
    best = min(fresh, key=key)
    # Below, a watch's lock state is unknown: guess from stillness and confidence.
    if best.get("cls") == "phone" and key(best)[0]:
        # Everything is stationary: a watch placed at least as well as the phone
        # beats it, since the phone is likelier to have been set down.
        pconf = best.get("conf") or 0.0
        # ...unless the phone went to another room when the watch had already lain
        # still for watch_still: the watch was left behind, the phone was carried.
        # On another floor a stay of RECENT_MOVE_SECS is proof enough: nobody wearing
        # the watch is down there with the phone, and near-equal confidences would
        # otherwise swap the two every cycle.
        went = best.get("arrived")
        asked = watch_still > 0 and isinstance(went, (int, float))
        known = lambda f: f not in (None, "", "unknown")

        def left_behind(t):
            if not (asked and (t.get("zone"), t.get("floor")) != (best.get("zone"), best.get("floor"))
                    and isinstance(t.get("arrived"), (int, float))):
                return False
            far = known(t.get("floor")) and known(best.get("floor")) and t["floor"] != best["floor"]
            return t["arrived"] <= went - (min(watch_still, RECENT_MOVE_SECS) if far else watch_still)

        watches = [t for t in fresh if t.get("cls") == "watch" and t.get("conf") is not None and t["conf"] >= pconf
                   and not left_behind(t)]
        if watches:
            return min(watches, key=key)
    return best


def considered(things, now):
    """What the choice was between, for the location sensor: each thing that
    gives its owner's location, where it is and since when it has stayed
    there. Shows why the person reads where they do.

    A time, not a count of minutes: a count ticks every minute and would
    write a recorder row each time while nobody moves. A thing with no
    position to measure a stay from (its arrival reads as "now", every
    cycle) gives None."""
    return [
        {"thing": t["ent"], "where": t.get("sub_zone") if t.get("sub_zone") not in (None, "", "unknown") else t.get("zone"),
         "here_since": _iso(t.get("arrived"), now),
         **({"on_charger": True} if t.get("on_charger") else {}),
         **({"worn": t["worn"]} if t.get("worn") is not None else {})}
        for t in things
    ]


def _iso(stamp, now):
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not math.isfinite(stamp) or stamp >= now:
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).replace(microsecond=0).isoformat()


# How far beyond the rooms a fix is, and what the fit looked like, published so
# "outside the house" can be told from "by a wall".
FIT_KEYS = FIT_ATTRIBUTES


def states(best, why=None):
    """(suffix -> (state, attributes)) for a person's sensors from the chosen thing."""
    if best is None:
        blank = {"room": "unknown", "spot": None, "floor": "unknown", "area_id": None, "floor_id": None, "via": None}
        return {
            "sextant_person_location": ("unknown", {"kind": "room", **blank}),
            "sextant_person_room": ("unknown", {"area_id": None, "via": None}),
            "sextant_person_floor": ("unknown", {"via": None}),
        }
    spot = best.get("sub_zone")
    spot = spot if spot not in (None, "", "unknown") else None
    room, floor = best.get("zone"), best.get("floor") or "unknown"
    area_id, floor_id = best.get("area") or (None, None)
    via = {"via": best["ent"]}
    dist = {k: best[k] for k in FIT_KEYS if best.get(k) is not None}
    if best.get("outside"):
        # Beyond every room: not the nearest room it was snapped into.
        return {
            "sextant_person_location": ("Outside", {"kind": "outside", "room": "Outside", "spot": None, "floor": floor,
                                                    "area_id": None, "floor_id": None, **via, **dist, "considered": why or []}),
            "sextant_person_room": ("Outside", {"area_id": None, **via}),
            "sextant_person_floor": (floor, via),
        }
    return {
        "sextant_person_location": (spot or room, {"kind": "spot" if spot else "room", "room": room, "spot": spot,
                                                   "floor": floor, "area_id": area_id, "floor_id": floor_id,
                                                   **via, **dist, "considered": why or []}),
        "sextant_person_room": (room, {"area_id": area_id, **via}),
        "sextant_person_floor": (floor, via),
    }


# --- BLE + GPS: where a person is when their things cannot say ----------------
# A person's things place them while they are home. Away, a GPS tracker (the
# Companion app, Life360) knows the zone. The two are fused here: BLE while it
# hears them (and held through a quiet spell - the last place they were put is
# the best answer for a few minutes), the first GPS source that is neither
# broken nor stale once BLE has lost them - or another whose newer fix shows
# them gone, or back (choose_gps).

GPS_STALE_SECS = 7200.0            # a tracker that has not reported for this long is ignored
_DEAD = (None, "", "unknown", "unavailable")
STATIONARY_ZONE_PREFIX = "zone.ic3_stationary_"   # iCloud3's zone.ic3_stationary_1, _2, ...
_STATIONARY_NAME = re.compile(r"StatZon\d*")       # its default friendly name, StatZon#


def stationary_zone(zone, attrs=None) -> bool:
    """Whether a tracker's zone is an iCloud3 Stationary Zone: the 100 m
    circle iCloud3 draws round a phone that has stopped somewhere away from
    home, so it can poll it less often. It is a polling device, not a place -
    nobody wants "StatZon1" as their location - so Sextant reads it as
    not_home and keeps the coordinates. Known by the zone's entity id in the
    tracker's ``in_zones`` (whatever it has been renamed to), or by iCloud3's
    default name when the tracker carries no list."""
    zones = (attrs or {}).get("in_zones")
    if isinstance(zones, (list, tuple)) and any(str(z).startswith(STATIONARY_ZONE_PREFIX) for z in zones):
        return True
    return bool(_STATIONARY_NAME.fullmatch(str(zone or "")))
_PRESENCE_RANK = {"here": 0, "quiet": 1, "away": 2}


def gps_sources(layout, person) -> list[str]:
    """The person's GPS trackers, in the order they are to be tried."""
    raw = layout.get("person_trackers") if isinstance(layout, dict) else None
    lst = raw.get(person) if isinstance(raw, dict) else None
    return [x for x in lst if isinstance(x, str) and x.startswith("device_tracker.")] if isinstance(lst, list) else []


def judge_source(entity_id, state, now, stale_secs=GPS_STALE_SECS):
    """Whether one tracker is usable right now: ``(ok, reason, info)``.

    Broken (no entity, unknown/unavailable) and stale (no report within
    stale_secs - a Companion app that has lost its location permission sits
    on its last fix for days) are both disregarded, and the reason is kept so
    the Things page can say why. A tracker with a zone but no coordinates
    (some router-style ones) still tells the zone.
    """
    if state is None:
        return False, "not found", None
    st = getattr(state, "state", None)
    if st in _DEAD:
        return False, str(st or "empty"), None
    attrs = getattr(state, "attributes", None) or {}
    stamps = [t for t in (getattr(state, "last_reported", None), getattr(state, "last_updated", None)) if t is not None]
    reported = max((t.timestamp() if hasattr(t, "timestamp") else float(t)) for t in stamps) if stamps else None
    if reported is not None and now - reported > stale_secs:
        return False, f"no report for {(now - reported) / 3600:.1f} h", None
    lat, lon = attrs.get("latitude"), attrs.get("longitude")
    # On the globe: anything else (an infinity, a NaN) would raise in the distance sum.
    coords = (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
              and -90 <= lat <= 90 and -180 <= lon <= 180)
    stationary = stationary_zone(st, attrs)
    accuracy, updated = (attrs.get("gps_accuracy") if coords else None), getattr(state, "last_updated", None)
    try:
        # An int no float can hold would raise in the distance guard (gps_left), a NaN or an
        # infinity where the tracker entity rounds it: each would stop everyone's update.
        if not math.isfinite(float(accuracy)):
            accuracy = None
    except (TypeError, ValueError, OverflowError):
        accuracy = None
    return True, None, {
        "entity": entity_id, "zone": "not_home" if stationary else st, "stationary": stationary,
        "latitude": float(lat) if coords else None, "longitude": float(lon) if coords else None,
        "accuracy": accuracy, "reported": reported,
        "updated": updated.timestamp() if hasattr(updated, "timestamp") else None,   # the last write (usable_gps)
    }


def usable_gps(get_state, layout, person, now, stale_secs=GPS_STALE_SECS, fixes=None):
    """The person's usable GPS sources in their order, and the ones passed over.

    ``fixes`` (entity -> (place, when, the fix), kept by the caller from cycle
    to cycle) does two things. It times each fix: a source gets ``fix_at``,
    when its zone or coordinates last changed while Sextant was watching, None
    for the fix it started with. Home Assistant's own times will not do for
    telling which of two sources has the newer word (choose_gps): a restart
    stamps every state as new, a battery level moves last_updated, and a
    tracker back from unavailable has a new last_changed with the fix it had
    before. And it keeps a source's last fix while the source is out
    (unavailable, unknown, not found), until that fix is as old as any stale
    one: a tracker dropping out is no word about where the person is, so a
    departure it saw still stands, and a fix it had corrected stays corrected.
    Such a fix is marked ``out`` (the reason), and the source is still named as
    passed over: it counts only if it was made since the person was last heard
    (choose_gps). It is kept for stale_secs after the source's last report,
    and then the sources that are left speak again. Coordinates left out of a
    write, the zone unchanged, are the same place: the fix keeps them, and the
    time they were reported at.

    shortcut: the time is that of the write the cycle first sees the new place
    in, so another write in between (a battery level) dates it up to a cycle
    late, and a tracker back from an outage in a new place is dated at its
    return. Listen for the state changes instead if a departure is ever read
    from a fix made before the last sighting.
    """
    usable, ignored = [], []
    for eid in gps_sources(layout, person):
        ok, reason, info = judge_source(eid, get_state(eid), now, stale_secs)
        kept = (fixes or {}).get(eid)
        if not ok:
            if kept and now - (kept[2]["reported"] or 0.0) <= stale_secs:
                usable.append({**kept[2], "out": reason})
                reason += "; last fix kept"
            ignored.append({"entity": eid, "reason": reason})
            continue
        if fixes is not None:
            place = (info["zone"], info["latitude"], info["longitude"])
            # Not into an iCloud3 stationary zone (each is a new place under one name), and not
            # coordinates older than a stale tracker's.
            same_zone = (kept and kept[0][0] == place[0] and not (kept[2]["stationary"] or info["stationary"])
                         and now - (kept[2]["reported"] or 0.0) <= stale_secs)
            if same_zone and place[1] is None and kept[0][1] is not None:
                # The fix it had, coordinates and their time: without them a road fix would stop
                # showing them gone, and with a new time it would show them gone after a later sighting.
                place = kept[0]
                info.update({k: kept[2][k] for k in ("latitude", "longitude", "accuracy", "reported")})
            info["fix_at"] = None if kept is None else kept[1] if kept[0] == place else info["updated"]
            fixes[eid] = (place, info["fix_at"], info)
        usable.append(info)
    return usable, ignored


def has_exit(layout, floor, room) -> bool:
    """Whether the room has an outside door (its zone's ``exit``, set on the Edit page)."""
    for f in (layout or {}).get("floor") or []:
        if isinstance(f, dict) and f.get("name") == floor:
            return any(isinstance(z, dict) and z.get("entity_id") == room and z.get("exit") and not z.get("no_go")
                       for z in f.get("zones") or [])
    return False


def _exit_zones(layout):
    """(floor name, zone) of every room with an outside door."""
    for f in (layout or {}).get("floor") or []:
        for z in (f.get("zones") or []) if isinstance(f, dict) else []:
            if isinstance(z, dict) and z.get("exit") and not z.get("no_go"):
                yield f.get("name"), z


def exit_doors(layout) -> set[str]:
    """Every outside door's contact sensor (a room's ``exit_door``, set on the Edit page)."""
    return {z["exit_door"] for _, z in _exit_zones(layout) if isinstance(z.get("exit_door"), str) and z["exit_door"]}


def door_backs_exit(layout, held, opened, last_heard, window) -> bool:
    """Whether the doors allow that someone quiet at an outside door went out:
    an outside door was open within ``window`` seconds of when they were last
    heard (``opened``: contact -> when last seen open). Any outside door, not
    the held room's: they are held in the Foyer and out by the laundry door.
    True when it cannot be told: the room's own door has no sensor, or window is 0."""
    rooms = [z for floor, z in _exit_zones(layout)
             if floor == held.get("floor") and z.get("entity_id") in (held.get("zone"), held.get("zone_raw"))]
    if window <= 0 or any(not z.get("exit_door") for z in rooms):
        return True
    return any(abs(opened[d] - last_heard) <= window for d in exit_doors(layout) if d in opened)


def held_by_exit(layout, held) -> bool:
    """Whether a held place is at an outside door: its room, or the room its last fix fell in."""
    return any(has_exit(layout, held.get("floor"), z) for z in (held.get("zone"), held.get("zone_raw")))


def presence_of_things(presences) -> str:
    """A person is as present as their most present thing."""
    return min(presences, key=lambda p: _PRESENCE_RANK.get(p, 9)) if presences else "away"


def _haversine_m(a, b):
    import math  # noqa: PLC0415
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(d))


def gps_left(gps, last_heard, home=None, min_distance_m=200.0) -> bool:
    """Whether a GPS fix ends the quiet hold early: the person's things have
    gone quiet, and a tracker has reported since the last of them was heard,
    with a fix outside the home zone and at least min_distance_m from home
    (past its own accuracy). The hold is for a person who is still in the
    house but unheard for a few minutes; a phone five kilometres down the
    road is not that, and waiting out away_after_secs puts the departure a
    quarter of an hour late.

    Only a fix with coordinates counts: a zone-only tracker reads not_home
    the moment a phone drops off Wi-Fi, which happens in the house too. And
    only one made after the last sighting: a fix from before BLE last heard
    them says nothing about now. min_distance_m of 0 turns this off.
    """
    if not gps or min_distance_m <= 0 or str(gps.get("zone") or "").lower() == "home":
        return False
    reported, heard = valid_time(gps.get("reported")), valid_time(last_heard)
    if reported is None or (heard is not None and reported <= heard):
        return False
    lat, lon = gps.get("latitude"), gps.get("longitude")
    if lat is None or lon is None or not home or None in home:
        return False
    accuracy = gps.get("accuracy") if isinstance(gps.get("accuracy"), (int, float)) else 0.0
    return _haversine_m(home, (lat, lon)) - max(0.0, float(accuracy)) >= min_distance_m


def without_left_behind(candidates, gps, now, stale, home=None, min_distance_m=200.0):
    """(candidates that may still speak for the person, those left behind).
    A thing that came to rest (``arrived``) more than RECENT_MOVE_SECS ago and
    before a GPS fix far from home was made did not go with them (gps_left, the
    arrival standing for the last sighting): a watch on the bedside table while
    the phone is down the road. One that moved recently is never ruled out: it
    may be the very thing walking out, and one stray fix must not evict it.
    Only when the two agree: a phone still heard at home says GPS is wrong (or
    the phone is the thing left behind), so nothing is ruled out then. Nor
    when a watch heard and placed now says it is worn: it is on them, here."""
    if any((c.get("cls") == "phone" or (c.get("worn") and c.get("zone") not in (None, "", "unknown")))
           and isinstance(c.get("updated"), (int, float))
           and now - c["updated"] <= stale for c in candidates):
        return candidates, []
    left = [
        c for c in candidates
        if isinstance(c.get("arrived"), (int, float)) and now - c["arrived"] > RECENT_MOVE_SECS
        and gps_left(gps, c["arrived"], home, min_distance_m)
    ]
    return [c for c in candidates if c not in left], left


def choose_gps(usable, presence, last_heard, home=None, min_distance_m=200.0):
    """The GPS source that speaks for the person this cycle, of their usable
    ones in order (usable_gps).

    The first source speaks. But a phone app can sit on "home" for minutes
    into a drive while another service already has the car down the road. So
    once BLE has lost them (``presence`` of their things, ``last_heard``), the
    fixes Sextant saw arrive since they were last heard (``fix_at``) are
    weighed first. One that would end the quiet hold (gps_left) speaks, the
    first such in the person's order, unless a fix in the home zone is as new
    or newer: then they are back, and that one speaks where the first source
    does not say home itself (coming back, the app says home at the gate
    while the other still shows the road; a road fix made after that is the
    next departure). Nothing is remembered here from cycle to cycle: a source
    that drops out keeps its last fix (usable_gps), so what it saw still counts.
    Only that, though: a source that is out is never the first that speaks, or
    a collar that died while it said home would keep the dog home for hours.

    shortcut: someone heard right now (a watch left at home) or never heard
    (a visitor with GPS only) has no last sighting to hold a fix against, so
    only the first source speaks for them; and the fix times are not kept
    over a restart, after which a source counts this way only once it has
    moved. Upgrade when a departure is missed that way.
    """
    first, heard = next((g for g in usable if not g.get("out")), None), valid_time(last_heard)
    if presence == "here" or heard is None or min_distance_m <= 0:
        return first

    def at(g):
        return valid_time(g.get("fix_at")) or 0.0

    def is_home(g):
        return str(g.get("zone") or "").lower() == "home"

    since = [g for g in usable if at(g) > heard]
    # shortcut: only a fix in the home zone is "back". A source that said home and then drifts out of
    # the zone by the house no longer holds off another's older road fix; a fix by the house cannot
    # stand in for it (the app's zone-exit fix lands there on the way out). Remember when each source
    # last said home if that shows up.
    back = max((g for g in since if is_home(g)), key=at, default=None)
    gone = [g for g in since if (back is None or at(g) > at(back)) and gps_left(g, heard, home, min_distance_m)]
    if gone:
        return gone[0]
    return first if back is None or (first and is_home(first)) else back


def should_ask_gps(presence, placed, last_heard, asked_for) -> bool:
    """Whether to ask the person's phone for a location update now: they
    have just gone quiet (not placed, presence "quiet", which is already
    stale_after_secs since they were last heard) and have not been asked
    for this quiet spell.

    asked_for is the last_heard value of the last ask; a new last_heard means
    they were heard again and went quiet again, a new spell. Never twice in
    one: iOS throttles these silent pushes.
    """
    return (not placed and presence == "quiet" and valid_time(last_heard) is not None
            and asked_for != last_heard)


def wifi_outrun(gps, wifi_seen, home=None, min_distance_m=200.0, margin_secs=10.0) -> bool:
    """Whether GPS overrules a Wi-Fi tracker that still reads home: the
    router keeps a client "home" for minutes after it last saw the phone, so
    a departure read Kitchen on Wi-Fi with the phone 800 m down the road. A
    fix that would end the hold (gps_left), made over margin_secs after the
    access point last saw the client, says the Wi-Fi word is the stale one.

    Without a last-seen time (not a UniFi client) Wi-Fi stands: on an
    arrival the old far-away fix is the stale one, and nothing else tells
    the two apart.
    """
    seen = valid_time(wifi_seen)
    return seen is not None and gps_left(gps, seen + margin_secs, home, min_distance_m)


def visit_events(before, after, pets=()) -> list:
    """The bus events one cycle's visits make: ``[(event_type, data)]``.

    ``sextant_person_arrived`` / ``sextant_person_left`` when a person's
    tracker changes side, ``sextant_first_arrived`` when that fills an empty
    house and ``sextant_everyone_left`` when it empties it. "Everyone" is
    whoever was home: someone away for the term never holds it up. A person
    with no visit before (new, or a first start) makes no event, so nothing
    fires for the state Sextant merely found. Pets never count.
    """
    def is_home(v):
        return isinstance(v, dict) and valid_time(v.get("arrived")) is not None

    people = sorted(p for p in after if p not in pets)
    home_before = {p for p in people if is_home(before.get(p))}
    home_now = [p for p in people if is_home(after[p])]
    arrived = [p for p in home_now if p in before and p not in home_before]
    left = [p for p in people if p in home_before and not is_home(after[p])]
    out = []
    for p in arrived:
        out.append(("sextant_person_arrived", {"person": p, "source": after[p].get("via"),
                                               "time": visit_attrs(after[p])["arrived_at"], "people_home": home_now}))
    for p in left:
        out.append(("sextant_person_left", {"person": p, "source": before[p].get("via"),
                                            "time": visit_attrs(after[p])["departed_at"], "people_home": home_now}))
    if arrived and not home_before:
        first = min(arrived, key=lambda p: after[p]["arrived"])
        out.append(("sextant_first_arrived", {"person": first, "source": after[first].get("via"),
                                              "time": visit_attrs(after[first])["arrived_at"]}))
    if left and not home_now:
        last = max(left, key=lambda p: valid_time(after[p].get("departed")) or 0.0)
        out.append(("sextant_everyone_left", {"person": last, "source": before[last].get("via"),
                                              "time": visit_attrs(after[last])["departed_at"]}))
    return out


def room_changes(baseline, pending, now, pets=()):
    """``(baseline, pending, events)`` for ``sextant_person_room_changed``.

    ``now`` maps a person to ``(room, floor)`` while a sensor puts them in a
    room (None otherwise). A new place must read the same on two cycles in a
    row before it counts, so one stray fix makes nothing; the event fires only
    for a move from one place to another (arriving and leaving have their own
    events), and a person new to the map just sets their baseline. People no
    longer in ``now`` drop out of both maps."""
    base, pend, out = {}, {}, []
    for p in sorted(now):
        place = now[p]
        if p in pets:
            continue
        old = baseline.get(p)
        if p not in baseline or place == old:
            base[p] = place if p not in baseline else old
        elif pending.get(p) == place:
            base[p] = place
            if old and place:
                out.append(("sextant_person_room_changed", {"person": p, "from_room": old[0], "from_floor": old[1],
                                                             "room": place[0], "floor": place[1]}))
        else:
            base[p], pend[p] = old, place
    return base, pend, out


def fuse(best, why, presence, held, gps, ignored, home=None, wifi=None, dog=False):
    """(suffix -> (state, attributes)) for a person's sensors, BLE, Wi-Fi and GPS fused.

    here: the thing that speaks for them (states). quiet: the place they were
    last put, held - a person unheard for a few minutes is still in the house.
    Then Wi-Fi: BLE has lost them but a phone or watch of theirs is still
    joined to a home access point, so they are home, in the room that access
    point most often means (wifi: {"entity", "home", "ap", "floor", "room",
    "area_id", "floor_id"}; see wifi.py). away: the GPS zone, or "away" with
    nothing usable; a dog (``dog``) whose collar says home while no proxy
    hears her is in the garden: Outside. The location sensor always carries the GPS side too
    (zone, coordinates, distance from home), so a dashboard can show both.
    """
    gps_attrs = {"zone": None, "latitude": None, "longitude": None, "gps_accuracy": None, "tracker": None, "distance_m": None}
    if gps:
        gps_attrs.update(zone=gps.get("zone"), latitude=gps.get("latitude"), longitude=gps.get("longitude"),
                         gps_accuracy=gps.get("accuracy"), tracker=gps.get("entity"))
        if home and None not in home and gps.get("latitude") is not None:
            gps_attrs["distance_m"] = round(_haversine_m(home, (gps["latitude"], gps["longitude"])))
    # Capped: an attribute list has no business being long, and a state
    # write over Home Assistant's 16 KB attribute limit is refused.
    common = {"presence": presence, "gps_ignored": list(ignored or [])[:20]}
    if presence in ("here", "quiet") and (best or held):
        out = states(best or held, why)
        source = "ble" if best else "held"
        for suffix, (_st, attrs) in out.items():
            attrs["source"] = source
            attrs["presence"] = presence
        out["sextant_person_location"][1].update({**gps_attrs, "gps_ignored": common["gps_ignored"]})
        return out
    if wifi and wifi.get("home"):
        # Home, not a room: an access point's most frequent room is a guess
        # (the garage one read as Kitchen), good enough for a floor only.
        room, floor = "unknown", wifi.get("floor") or "unknown"
        via = wifi.get("entity")
        where = {"kind": "room", "room": room, "spot": None, "floor": floor, "area_id": None, "floor_id": wifi.get("floor_id"), "via": via}
        return {
            "sextant_person_location": ("home", {**where, "source": "wifi", "access_point": wifi.get("ap_name") or wifi.get("ap"), **common, **gps_attrs, "considered": why or []}),
            "sextant_person_room": (room, {"area_id": None, "via": via, "source": "wifi", "presence": presence}),
            "sextant_person_floor": (floor, {"via": via, "source": "wifi", "presence": presence}),
        }
    if gps:
        zone = gps.get("zone")
        state, source = ("away" if zone == "not_home" else zone), "gps"
    else:
        state, source = "away", "none"
    blank = {"kind": "zone", "room": "unknown", "spot": None, "floor": "unknown", "area_id": None, "floor_id": None, "via": None}
    if dog and state == "home":
        state, blank = "Outside", {**blank, "kind": "outside", "room": "Outside"}
    return {
        "sextant_person_location": (state, {**blank, "source": source, **common, **gps_attrs, "considered": why or []}),
        "sextant_person_room": (blank["room"], {"area_id": None, "via": None, "source": source, "presence": presence}),
        "sextant_person_floor": ("unknown", {"via": None, "source": source, "presence": presence}),
    }


def keep_since(prev, attrs, arrived=None):
    """A person's room and spot times are theirs, not the tracking thing's: when the
    phone takes over from the watch in the same room, ``since`` stays when they came
    in, not when the phone did. ``prev`` is the location sensor's last attributes;
    a time from before ``arrived`` (this home visit) is an earlier visit's, held over."""
    prev = prev or {}
    if attrs.get("room") in (None, "unknown") or attrs.get("kind") == "outside":
        return attrs
    for key, same in (("since", ("floor", "room")), ("spot_since", ("floor", "room", "spot"))):
        old = prev.get(key)
        if (isinstance(old, (int, float)) and not (isinstance(arrived, (int, float)) and old < arrived) and all(prev.get(k) == attrs.get(k) for k in same)
                and (key == "since" or attrs.get("spot"))):
            attrs[key] = old
    return attrs


def wifi_gate(wifi, since, prev_visit, now, confirm_secs):
    """(since, wifi): Wi-Fi's home word, held back until it has stood for
    confirm_secs when it would START a visit. A router keeps a client "home"
    for minutes after the phone left the garage and a quiet BLE spell can end
    on it, which made a false arrival minutes before the real departure. A
    visit already under way is carried on at once (BLE lost in a dead zone,
    a flat watch), so is a word with nothing to start. ``since`` is when the
    unbroken run began, None while there is no word."""
    if not wifi:
        return None, None
    since = valid_time(since)
    since = now if since is None else since
    prev = prev_visit if isinstance(prev_visit, dict) else {}
    if confirm_secs <= 0 or valid_time(prev.get("arrived")) is not None or now - since >= confirm_secs:
        return since, wifi
    return since, None


def valid_time(t):
    """``t`` as a float epoch second, or None: a number (not a bool), finite,
    and one datetime can represent, so nothing downstream ever raises on it.
    Everything happens inside the try: even math.isfinite raises on an int
    too big for a float."""
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


def home_via(presence, gps, wifi=None):
    """What makes the person's tracker read home: ``"ble"`` (here or quiet),
    ``"wifi"`` (BLE has lost them but a phone or watch of theirs is still
    joined to a home access point), ``"gps"`` (the GPS fix is in the home
    zone), or None when it reads away."""
    if presence in ("here", "quiet"):
        return "ble"
    if wifi and wifi.get("home"):
        return "wifi"
    if gps and str(gps.get("zone") or "").lower() == "home":
        return "gps"
    return None


def tracker_home(presence, gps, wifi=None) -> bool:
    """Whether the person's tracker reads home (see home_via)."""
    return home_via(presence, gps, wifi) is not None


def visit(prev, via, last_heard, now):
    """The person's current visit: ``{"arrived": t, "departed": None, "via"}``
    while the tracker reads home, ``{"arrived": None, "departed": t}`` once
    away - exactly one of the two holds a time, matching the tracker's state,
    so an automation can trigger on the attribute leaving None and get one
    clean event with the time in it. ``via`` is home_via's answer.

    The time is the evidence's own. Home on BLE: the arrival is the sighting
    that brought them back, and a departure the last sighting before the
    house fell silent - not when away_after_secs ran out ("left at 08:12"
    means 08:12), the quiet period being the grace. Home on GPS alone (BLE
    silent since the morning, the phone's GPS back in the zone at six): the
    arrival is when GPS said so, and a departure that GPS decides is stamped
    when GPS left the zone, not at a BLE sighting hours earlier. Nothing
    changes while the state holds, so the recorder gets a row per event.
    """
    prev = prev if isinstance(prev, dict) else {}
    arrived, departed = valid_time(prev.get("arrived")), valid_time(prev.get("departed"))
    heard, now_t = valid_time(last_heard), valid_time(now) or 0.0
    ble_time = heard if heard is not None else now_t
    if via:
        if arrived is not None and departed is None:
            if prev.get("via") == via:
                return prev
            return {**prev, "via": via}          # the same visit, now carried by the other source
        return {"arrived": ble_time if via == "ble" else now_t, "departed": None, "via": via}
    if departed is not None and arrived is None:
        return prev
    # Leaving: BLE silence is dated by the last sighting; GPS leaving the zone, by now.
    return {"arrived": None, "departed": ble_time if prev.get("via", "ble") == "ble" else now_t}


def visit_attrs(v) -> dict:
    """``arrived_at`` / ``departed_at`` as ISO 8601 UTC, for the tracker."""
    def iso(t):
        t = valid_time(t)
        return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds") if t else None
    v = v if isinstance(v, dict) else {}
    return {"arrived_at": iso(v.get("arrived")), "departed_at": iso(v.get("departed"))}


def tracker_fix(presence, gps, visit=None, wifi=None):
    """What the person's device_tracker reports: home on BLE's word (it is far
    surer of "in the house" than GPS at the property line), home on Wi-Fi's
    once BLE has lost them but a phone or watch is still joined to a home
    access point, the GPS fix after that, not_home with nothing usable.
    ``visit`` adds when they arrived or left (see visit)."""
    when = visit_attrs(visit)
    if presence in ("here", "quiet"):
        return {"location_name": "home", "source_type": "bluetooth_le", "source": "ble", "presence": presence, **when}
    if wifi and wifi.get("home"):
        return {"location_name": "home", "source_type": "router", "source": "wifi", "presence": presence, "tracker": wifi.get("entity"), **when}
    if gps and gps.get("latitude") is not None:
        # Coordinates decide, except in an iCloud3 Stationary Zone: Home
        # Assistant would name that zone from the coordinates, so the tracker
        # says not_home outright and carries the coordinates beside it.
        return {"location_name": "not_home" if gps.get("stationary") else None, "latitude": gps["latitude"], "longitude": gps["longitude"],
                "accuracy": gps.get("accuracy"), "source_type": "gps", "source": "gps", "presence": presence, "tracker": gps.get("entity"), **when}
    if gps:
        return {"location_name": gps.get("zone"), "source_type": "gps", "source": "gps", "presence": presence, "tracker": gps.get("entity"), **when}
    return {"location_name": "not_home", "source_type": "gps", "source": "none", "presence": presence, **when}
