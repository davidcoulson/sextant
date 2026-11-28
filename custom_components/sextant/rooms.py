"""Who is in each room: the per-room occupancy sensors.

Sextant's other sensors answer "where is this thing?" and "where is this
person?". These answer the question an automation about a room asks -
"is anyone in the Kitchen, and who?" - as one binary sensor per room,
``on`` while any tracked thing is placed there, with the people, pets and
things as attributes. It is also the shape an occupancy aggregator such as
Area Occupancy Detection takes as an input: a binary that carries identity.

Pure: no Home Assistant imports, so it loads in the unit tests. The
platform (binary_sensor.py) and the cycle hook (__init__._update_room_sensors)
do the plumbing.
"""
from __future__ import annotations

import hashlib
import math
import re

PET_CLASSES = frozenset({"cat", "dog", "paw"})

# Presence states that keep a thing counted in its room: heard lately, or
# not heard for a few minutes but still placed (the room sensor holds its
# value through that gap too). "away" drops it.
COUNTED = ("here", "quiet")
_RANK = {"here": 0, "quiet": 1}

# How long a stay lifts the confidence in a room call. A stay shows the call is
# stable, not that it is right (a wrong room can sit there for hours), so it
# closes at most DWELL_MAX_GAIN of the gap between the fit's confidence and 1,
# and gets 63 % of that by DWELL_TAU_S.
DWELL_MAX_GAIN = 0.5
DWELL_TAU_S = 600.0


def settled_confidence(conf, dwell_s, presence="here"):
    """The fit's ``conf`` (0..1) lifted by how long the thing has stayed in the room.

    Only while it is heard ("here"): a quiet thing's long stay is a last known
    place, not fresh evidence. No stay, no conf, or any other presence leaves
    ``conf`` as it was.
    """
    if conf is None or presence != "here" or not dwell_s or dwell_s <= 0:
        return conf
    return conf + (1.0 - conf) * DWELL_MAX_GAIN * (1.0 - math.exp(-dwell_s / DWELL_TAU_S))


def settled_conf_of(attrs, now, floor=None):
    """``settled_confidence`` for a location sensor's attributes, rounded for
    publishing; None when they carry no conf or stay, or the thing is outside
    (no room call to settle). The stay is the room's, as the popup's "Here for"
    is: moving from the couch to the rug is no reason to doubt the room.
    ``floor`` is the earliest time a stay may count from (a person's arrival
    this visit: a tracker's earlier tenure is not theirs). A time that is not a
    plain number is no stay."""
    since = attrs.get("since")
    if isinstance(since, bool) or not isinstance(since, (int, float)) or not math.isfinite(since):
        return None
    if isinstance(floor, (int, float)) and not isinstance(floor, bool):
        since = max(since, floor)
    if attrs.get("conf") is None or attrs.get("kind") == "outside":
        return None
    return round(settled_confidence(attrs["conf"], now - since, attrs.get("presence")), 3)


def slug(text: str) -> str:
    """A lower-case entity-id-safe slug: 'Great Room' -> 'great_room'."""
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return s or "room"


def room_keys(layout) -> list[dict]:
    """Every room on every floor, with its links: [{floor, room, area_id, floor_id}].

    No-go zones are not rooms. Order is the layout's: floors as listed,
    rooms as listed, so the sensors appear the way the plan reads.
    """
    out = []
    floors = layout.get("floor") if isinstance(layout, dict) else None
    for floor in floors or []:
        if not isinstance(floor, dict) or not floor.get("name"):
            continue
        floor_id = floor.get("floor_id") if isinstance(floor.get("floor_id"), str) else None
        for zone in floor.get("zones") or []:
            if not isinstance(zone, dict) or zone.get("no_go") or not zone.get("entity_id"):
                continue
            area = zone.get("area_id")
            out.append({"floor": floor["name"], "room": zone["entity_id"],
                        "area_id": area if isinstance(area, str) and area else None, "floor_id": floor_id,
                        **room_options(zone)})
    return out


def _secs(value, low, high):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high
    return float(value) if ok else None


def _entity_ids(value) -> list[str]:
    """Entity ids from a list or a comma/space separated string; anything else is dropped."""
    if isinstance(value, str):
        value = re.split(r"[,\s]+", value)
    return [v.strip() for v in value if isinstance(v, str) and re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*\.[a-z0-9]+(_[a-z0-9]+)*", v.strip())] if isinstance(value, list) else []


_ENTITY = r"[a-z0-9]+(?:_[a-z0-9]+)*\.[a-z0-9]+(?:_[a-z0-9]+)*"
_SPEC = re.compile(rf"({_ENTITY})(?:(>=|<=|>|<)(-?[0-9]+(?:\.[0-9]+)?))?")


def _input_specs(value) -> list[str]:
    """Inputs from a list or a comma/space separated string: an entity id, or one with a
    number test (``sensor.tv_power>20``, ``sensor.lux<5``); anything else is dropped."""
    if isinstance(value, str):
        value = re.split(r"[,\s]+", re.sub(r"\s*(>=|<=|>|<)\s*", r"\1", value))
    return [v.strip() for v in value if isinstance(v, str) and _SPEC.fullmatch(v.strip())] if isinstance(value, list) else []


def spec_entity(spec: str) -> str:
    return _SPEC.fullmatch(spec).group(1)


def room_options(zone) -> dict:
    """A room's own settings, read from its zone (``room_hold_secs``, ``room_extended_secs``,
    ``inputs``, ``door``) and made safe: ``hold_secs`` and
    ``extended_secs`` (None = the global tuning), ``inputs`` (other entities that
    say someone is in the room: motion, media players, a presence sensor, or a
    number past a threshold such as a TV's power draw) and
    ``door`` (a contact entity whose closed state keeps the room occupied)."""
    door = _entity_ids(zone.get("door"))
    # Never a Sextant occupancy sensor (it would hold itself on) nor the door (an open door is not a person).
    def specs(value):
        return [e for e in _input_specs(value) if not re.search(r"sextant.*occupancy(_\d+)?$", spec_entity(e)) and spec_entity(e) not in door]
    inputs = specs(zone.get("inputs"))
    mode, sleep, dark = _entity_ids(zone.get("mode_entity")), _entity_ids(zone.get("sleep_entity")), _input_specs(zone.get("dark"))
    label = zone.get("mode_label")
    return {"hold_secs": _secs(zone.get("room_hold_secs"), 0.0, 3600.0), "extended_secs": _secs(zone.get("room_extended_secs"), 30.0, 86400.0),
            "inputs": inputs, "door": door[0] if door else None,
            # Sensors that keep an occupied room on but never turn an empty one on (a TV, a flappy tracker).
            "keep": [e for e in specs(zone.get("keep")) if e not in inputs],
            # The room's mode (mode_of), whether it is dark (is_dark) and whether someone sleeps there, each from one entity.
            "mode_entity": mode[0] if mode else None,
            "mode_label": label.strip()[:40] if isinstance(label, str) and label.strip() else None,
            "dark": dark[0] if dark else None, "sleep_entity": sleep[0] if sleep else None,
            # Clear-after while asleep or once extended (None = the global tuning, which may itself say "as usual").
            "sleep_hold_secs": _secs(zone.get("room_sleep_hold_secs"), 0.0, 86400.0),
            "extended_hold_secs": _secs(zone.get("room_extended_hold_secs"), 0.0, 86400.0)}


# States that mean "nothing" for a mode entity; anything else that is not an "on" state is the mode's own name.
_NO_MODE = {"", "off", "idle", "standby", "paused", "none", "unknown", "unavailable", "not_home", "false"}


def mode_of(state, label=None, option=False):
    """The room's mode from its mode entity's state: a dropdown's option as it is
    (``option``: "Movie", and "Idle" or "Home" too), ``label`` (or "on") while an
    on/off entity is on, None otherwise."""
    text = str(state if state is not None else "").strip()
    if option:
        return None if text.lower() in ("", "unknown", "unavailable") else text[:40]
    if text.lower() in _NO_MODE:
        return None
    return (label or "on") if text.lower() in ACTIVE_STATES else text[:40]


def is_dark(spec, get_state):
    """True/False from the room's ``dark`` entity (on = dark, or a number test such
    as ``sensor.lux<20``), or from the sun when the room has none; None when unknown."""
    if spec:
        state = get_state(spec_entity(spec))
        return None if state in (None, "unknown", "unavailable") else _input_on(spec, state)
    sun = get_state("sun.sun")
    return {"below_horizon": True, "above_horizon": False}.get(sun)


def hold_for(asleep, extended, hold_s, sleep_s=None, extended_s=None):
    """The clear-after that applies now: the sleep one while someone sleeps here,
    the extended one after a long stay, else the usual. None or negative = the usual."""
    for on, secs in ((asleep, sleep_s), (extended, extended_s)):
        if on and isinstance(secs, (int, float)) and secs >= 0:
            return float(secs)
    return hold_s


# States that say "someone is here" for a motion/presence/occupancy sensor, a
# person or tracker, and a media player. Contact sensors are not inputs: a door
# is the room's ``door``, not evidence of a person.
ACTIVE_STATES = {"on", "home", "playing", "occupied", "detected"}


def _input_on(spec, state) -> bool:
    m = _SPEC.fullmatch(spec)
    if not m.group(2):
        return str(state or "").lower() in ACTIVE_STATES
    try:
        value, limit = float(state), float(m.group(3))
    except (TypeError, ValueError):
        return False   # unavailable or text: not evidence
    if not (math.isfinite(value) and math.isfinite(limit)):
        return False
    return {">": value > limit, ">=": value >= limit, "<": value < limit, "<=": value <= limit}[m.group(2)]


def inputs_on(inputs, get_state) -> list[str]:
    """The ``inputs`` whose state says someone is there; ``get_state(entity_id)`` gives the state string."""
    return [e for e in inputs or [] if _input_on(e, get_state(spec_entity(e)))]


def sensor_problems(keys, get, now, stuck_s, gone_s, bad_since=None, on_since=None) -> dict[str, dict]:
    """Room sensors (inputs and doors) that look broken, by entity id: ``{"kind", "age", "rooms"}``.

    ``missing``: no such entity for ``gone_s``. ``gone``: unavailable or unknown (either, in
    any order) for ``gone_s``, except a media player (a TV reads unavailable when off). ``stuck``: a binary sensor that has read on for ``stuck_s`` - it
    keeps its room occupied, so a motion sensor with a dead battery or a wedged mmWave shows here.
    Numbers (they change all the time), media players and trackers (a person can be home for
    days) are never called stuck. ``get(entity_id)`` gives a state object or None; ``bad_since``
    (kept by the caller between calls) times how long each has been missing or unavailable, and
    ``on_since`` each binary sensor's ``[on since, last_changed seen]``: last_changed starts again
    with Home Assistant, so the caller saves both over a restart and hands the saved time back as
    ``[since, None]``, which wins over the first last_changed seen after it.
    """
    bad_since = {} if bad_since is None else bad_since
    on_since = {} if on_since is None else on_since
    seen_on = set()
    out: dict[str, dict] = {}
    seen_bad = set()
    for key in keys:
        room = f"{key['room']} ({key['floor']})"
        for spec in (key.get("inputs") or []) + (key.get("keep") or []) + ([key["door"]] if key.get("door") else []):
            ent = spec_entity(spec)
            st = get(ent)
            found = None
            if st is not None and ent.startswith("media_player.") and ent != key.get("door") and str(st.state).lower() in ("unavailable", "unknown"):
                continue   # a TV that is switched off reads unavailable: normal, not broken
            if st is None or str(st.state).lower() in ("unavailable", "unknown"):
                seen_bad.add(ent)
                seen_on.add(ent)   # its on clock waits: every sensor reads unavailable while Home Assistant starts
                since = bad_since.setdefault(ent, now)
                age = now - since if st is None else max(now - since, now - st.last_changed.timestamp())
                if age >= gone_s:
                    found = {"kind": "missing" if st is None else "gone", "age": max(0.0, age)}
            elif ent.startswith("binary_sensor.") and spec == ent and ent != key.get("door") and str(st.state).lower() == "on":
                seen_on.add(ent)
                changed = st.last_changed.timestamp()
                since, seen = on_since.get(ent) or (changed, None)
                # A last_changed that moves after it was seen is a new on spell (off and on between
                # two calls); one not seen yet is the restart, and the saved time stands.
                on_since[ent] = [changed if seen not in (None, changed) else min(since, changed), changed]
                age = max(0.0, now - on_since[ent][0])
                if age >= stuck_s:
                    found = {"kind": "stuck", "age": age}
            if found:
                rooms = out.setdefault(ent, {**found, "rooms": []})["rooms"]
                if room not in rooms:
                    rooms.append(room)
    for ent in set(bad_since) - seen_bad:
        del bad_since[ent]
    for ent in set(on_since) - seen_on:
        del on_since[ent]
    return out


def door_closed(state):
    """True closed, False open, None unknown (no door, unavailable): a contact
    binary sensor reads ``on`` when open; a cover or lock says closed/open."""
    state = str(state or "").lower()
    if state in ("off", "closed", "locked"):
        return True
    return False if state in ("on", "open", "unlocked") else None


def ids_for(keys) -> dict[tuple[str, str], dict]:
    """(floor, room) -> {slug, unique_id, entity_id, name}.

    The entity id is the room's name alone - ``binary_sensor.kitchen_sextant_occupancy``
    - unless two floors have a room of that name, when both get the floor in
    front. The unique id always carries the floor, so a room renamed on one
    floor does not take over another's history.
    """
    # Two different names that slug the same ("Guest Room", "Guest-Room") on
    # one floor would be one sensor: each then carries a few characters of
    # its exact name - both of them, so neither depends on which was drawn
    # first. (Deleting one of such a pair still lets the other drop its
    # suffix; the platform migrates the registry entry when that happens.)
    names_by_slug: dict[tuple[str, str], set[str]] = {}
    for k in keys:
        names_by_slug.setdefault((k["floor"], slug(k["room"])), set()).add(k["room"])
    room_slugs: dict[tuple[str, str], str] = {}
    for k in keys:
        base = slug(k["room"])
        twins = len(names_by_slug[(k["floor"], base)]) > 1
        room_slugs[(k["floor"], k["room"])] = f"{base}_{hashlib.sha1(k['room'].encode()).hexdigest()[:6]}" if twins else base
    by_room: dict[str, int] = {}
    for rs in room_slugs.values():
        by_room[rs] = by_room.get(rs, 0) + 1
    out = {}
    for k in keys:
        room_slug = room_slugs[(k["floor"], k["room"])]
        shared = by_room[room_slug] > 1
        shown = f"{slug(k['floor'])}_{room_slug}" if shared else room_slug
        out[(k["floor"], k["room"])] = {
            "slug": shown,
            "unique_id": f"sextant_room_occupancy_{slug(k['floor'])}_{room_slug}",
            "entity_id": f"binary_sensor.{shown}_sextant_occupancy",
            "name": f"{k['room']} ({k['floor']}) Sextant Occupancy" if shared else f"{k['room']} Sextant Occupancy",
        }
    return out


def occupancy(keys, rows, presence_of, classes=None, names=None, person_rooms=None, stands_for_someone=None) -> dict[tuple[str, str], tuple[bool, dict]]:
    """The state and attributes of every room's sensor.

    ``rows`` are the cycle's position rows ({ent, zone, floor, sub_zone, ...});
    ``presence_of(ent)`` gives here / quiet / away; ``classes`` and ``names``
    are the layout's thing classes and display names; ``person_rooms`` is
    {person display name: (floor, room)} for each person Sextant currently
    places (from the person sensors), so a person is listed in the room the
    thing speaking for them is in, not in every room one of their things is.

    Occupancy is about people and pets. A room is ``on`` while something
    that stands for someone is in it - a phone, a watch, a pet's tag
    (``stands_for_someone(ent)``, persons.locates_owner by default) - or a
    person is placed there. A wallet left on the counter or luggage in a
    bedroom is listed under ``things`` but does not make the room occupied,
    and a robot vacuum is not a thing here at all.
    """
    classes = classes or {}
    names = names or {}
    if stands_for_someone is None:
        def stands_for_someone(ent):
            return classes.get(ent) in PET_CLASSES or classes.get(ent) in ("phone", "watch", "person", "man", "woman", "child")
    by_key: dict[tuple[str, str], list[tuple[str, str, str | None, bool]]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("robot"):
            continue
        ent, zone, floor = row.get("ent"), row.get("zone"), row.get("floor")
        # Outside: the zone is only the nearest room, and the thing is in none of them.
        if not ent or not zone or zone == "unknown" or not floor or row.get("outside"):
            continue
        presence = presence_of(ent)
        if presence not in COUNTED:
            continue
        spot = row.get("sub_zone")
        by_key.setdefault((floor, zone), []).append((ent, presence, spot if spot and spot != "unknown" else None, bool(stands_for_someone(ent))))
    people_by_key: dict[tuple[str, str], list[str]] = {}
    for person, where in (person_rooms or {}).items():
        if where:
            people_by_key.setdefault(tuple(where), []).append(person)
    out = {}
    for k in keys:
        key = (k["floor"], k["room"])
        here = sorted(by_key.get(key, []), key=lambda t: (_RANK[t[1]], names.get(t[0], t[0]).lower()))
        counted = [t for t in here if t[3]]
        things = [names.get(ent, ent) for ent, _p, _s, _c in here]
        pets = [names.get(ent, ent) for ent, _p, _s, _c in here if classes.get(ent) in PET_CLASSES]
        people = sorted(people_by_key.get(key, []))
        presence = min((p for _e, p, _s, _c in counted), key=_RANK.get, default=None)
        out[key] = (bool(counted) or bool(people), {
            "room": k["room"], "floor": k["floor"], "area_id": k["area_id"], "floor_id": k["floor_id"],
            "count": len(counted), "people": people, "pets": pets, "things": things,
            # Display name -> thing slug, so the panel can find each chip's sensors.
            "ids": {names.get(ent, ent): ent for ent, _p, _s, _c in here},
            "humans": sum(1 for t in counted if classes.get(t[0]) not in PET_CLASSES),
            "spots": sorted({s for _e, _p, s, _c in counted if s}),
            "presence": presence,
        })
    return out


def stands_for_someone(owners, speaking, by_class):
    """The counting rule for ``occupancy``: an owned thing counts only while it
    is the one speaking for its owner (``speaking``: the ``via`` of every
    person sensor) - a watch left on the bedside table while its owner's
    phone is in the kitchen is a watch, not a person. A thing nobody owns is
    judged by ``by_class(ent)`` alone (persons.locates_owner)."""
    owners = owners or {}
    speaking = set(speaking or ())

    def counts(ent):
        if owners.get(ent):
            return ent in speaking
        return bool(by_class(ent))
    return counts


def people_home(presences: dict[str, str], pets=()) -> tuple[int, dict]:
    """How many people Sextant hears in the house, from {person name: presence}.

    ``pets`` names the persons that are pets (Home Assistant lets a cat be a
    person): they are listed apart and not counted.
    """
    pets = set(pets)
    # BLE lost them but their phone is on the house's Wi-Fi, or a dog's collar says home: home
    at_home = (*COUNTED, "wifi", "gps")
    home = sorted(n for n, p in presences.items() if p in at_home and n not in pets)
    away = sorted(n for n, p in presences.items() if p not in at_home and n not in pets)
    pets_home = sorted(n for n, p in presences.items() if p in at_home and n in pets)
    return len(home), {"home": home, "away": away, "pets_home": pets_home}


def household_floor(home, floors: dict[str, str]) -> tuple[str, dict]:
    """The one floor everyone at home is on, from people_home's ``home`` list
    and {person name: floor} for those Sextant places on a floor.

    ``away`` with nobody home, ``mixed`` across floors, and ``unknown`` while
    anyone at home is on no floor (lost, outside, or held by Wi-Fi alone): the
    floor's name must mean nobody is anywhere else.
    """
    by_floor: dict[str, list] = {}
    for name in home:
        if name in floors:
            by_floor.setdefault(floors[name], []).append(name)
    unplaced = [n for n in home if n not in floors]
    state = "away" if not home else "unknown" if unplaced else next(iter(by_floor)) if len(by_floor) == 1 else "mixed"
    return state, {"floors": by_floor, "unplaced": unplaced}


def people_ids(ids) -> dict:
    """The people-only sensor of a room (on for a person, never for a pet's tag alone), from its ``ids_for`` entry."""
    return {
        "unique_id": ids["unique_id"].replace("sextant_room_occupancy_", "sextant_room_people_", 1),
        "entity_id": ids["entity_id"].replace("_sextant_occupancy", "_sextant_people_occupancy"),
        "name": ids["name"].replace("Sextant Occupancy", "Sextant People Occupancy"),
    }


def switch_ids(ids) -> dict:
    """The force-occupied switch of a room, from its ``ids_for`` entry. It
    shares the room's device, so it lands in the room's area with the sensor."""
    return {
        "unique_id": ids["unique_id"].replace("sextant_room_occupancy_", "sextant_room_force_", 1),
        "entity_id": ids["entity_id"].replace("binary_sensor.", "switch.", 1).replace("_sextant_occupancy", "_sextant_force_occupied"),
        "name": ids["name"].replace("Sextant Occupancy", "Force Occupied"),
    }


HOUSE_ID = {"unique_id": "sextant_house_occupancy", "entity_id": "binary_sensor.sextant_house_occupancy",
            "name": "Sextant House Occupancy"}


def floor_ids(keys) -> dict[str, dict]:
    """floor name -> {unique_id, entity_id, name} of its occupancy sensor.
    Floors whose names slug the same each carry a few characters of their exact name."""
    names = sorted({k["floor"] for k in keys})
    count: dict[str, int] = {}
    for f in names:
        count[slug(f)] = count.get(slug(f), 0) + 1
    out = {}
    for k in keys:
        f = k["floor"]
        if f in out:
            continue
        s = f"{slug(f)}_{hashlib.sha1(f.encode()).hexdigest()[:6]}" if count[slug(f)] > 1 else slug(f)
        out[f] = {"unique_id": f"sextant_floor_occupancy_{s}", "entity_id": f"binary_sensor.{s}_sextant_floor_occupancy",
                  "name": f"{f} Sextant Occupancy", "floor_id": k["floor_id"]}
    return out


def people_aggregate_ids(ids) -> dict:
    """The people-only twin of a floor's or the house's occupancy ids; it shares their device."""
    head, _, tail = ids["entity_id"].rpartition("_occupancy")
    uid = ids["unique_id"]
    for old, new in (("sextant_floor_occupancy_", "sextant_floor_people_occupancy_"), ("sextant_house_occupancy", "sextant_house_people_occupancy")):
        if uid.startswith(old):
            uid = new + uid[len(old):]
            break
    return {**ids, "unique_id": uid, "entity_id": f"{head}_people_occupancy{tail}",
            "name": ids["name"].replace("Occupancy", "People Occupancy"), "device_id": ids["unique_id"]}


def sources(things, radar, inputs, forced, door_hold, restoring, hold_over, kept=False) -> list:
    """Why a room is on, for its ``sources`` attribute: ``bluetooth`` (a tracked
    thing placed there), ``radar``, ``media_player`` / ``sensor`` (an input, named
    in ``inputs``), ``forced``, ``door`` (shut in), ``restored`` (carried over a
    restart), ``keep`` (only a keep-only sensor) and ``hold`` (nothing now, the clear-after hold still running)."""
    out = []
    for name, on in (("bluetooth", things), ("radar", radar)):
        if on:
            out.append(name)
    if any(str(e).startswith("media_player.") for e in inputs or []):
        out.append("media_player")
    if any(not str(e).startswith("media_player.") for e in inputs or []):
        out.append("sensor")
    for name, on in (("forced", forced), ("door", door_hold), ("restored", restoring), ("keep", kept), ("hold", hold_over)):
        if on:
            out.append(name)
    return out


def settle(prev, raw_on, now, hold_s=0.0, extended_s=600.0, door=None, door_settle_s=90.0, door_max_s=28800.0) -> dict:
    """A room's published state from this reading's ``raw_on``.

    ``on`` stays up for ``hold_s`` after the last reading that said occupied
    (Magic Areas' "clear after"), and ``state`` is ``occupied``, ``extended``
    once occupied for ``extended_s`` (a long stay: lights and climate can
    treat it differently) or ``clear``. ``since`` is when ``on`` last flipped.

    ``door`` is the room door's state (True closed, False open, None none or
    unknown). Someone who stays in the room for ``door_settle_s`` after the
    door closed has shut themselves in (a bedroom at night, a bathroom): the
    room stays on, however still they are, until the door opens or
    ``door_max_s`` passes. The wait is what tells them from someone who shut
    the door on the way out, who stops reading in the room within it.
    """
    prev = prev or {}
    last_raw = now if raw_on else prev.get("last_raw")
    shut, shut_at, closed_since = bool(prev.get("door_hold")), prev.get("door_at"), prev.get("door_closed_at")
    if door is None:
        pass   # unavailable or no door: keep what was known (a sleeper's hold survives a flaky contact sensor)
    elif door is False:
        shut = False
        closed_since = None
    else:
        if closed_since is None:
            closed_since = now
            shut = False
            shut_at = None
        if not raw_on and not shut:
            closed_since = float("inf")   # it left before the wait was up: not shut in, until the door reopens
        elif raw_on and not shut and closed_since != float("inf") and now - closed_since >= door_settle_s:
            shut, shut_at = True, now
    if shut and now - (shut_at if shut_at is not None else now) >= door_max_s:
        shut, closed_since = False, float("inf")   # a door that never opened (or whose sensor is gone): let go, and do not take hold again
    # A hold keeps a room on, never turns one that has cleared back on: a clear-after that grew since must not revive an old reading.
    on = bool(raw_on) or shut or (bool(prev.get("on")) and hold_s > 0 and last_raw is not None and now - last_raw < hold_s)
    since = prev.get("since") if prev.get("on") == on and prev.get("since") is not None else now
    state = "clear" if not on else ("extended" if now - since >= extended_s else "occupied")
    return {"on": on, "state": state, "since": since, "last_raw": last_raw,
            "door_hold": shut, "door_at": shut_at if shut else None, "door_closed_at": closed_since}


def release_if_elsewhere(memory, held_people, elsewhere) -> bool:
    """Let a door hold go when everyone it was holding for is now placed in
    another room (they left and shut the door behind them). Edits ``memory``
    (a settle() result) and says whether it did."""
    if memory.get("door_hold") and held_people and set(held_people) <= set(elsewhere):
        memory.update(door_hold=False, door_at=None, door_closed_at=float("inf"))
        return True
    return False


def aggregate(keys, answers) -> tuple[dict, tuple[bool, dict]]:
    """(floor -> (on, attrs), (on, attrs) for the house), from the rooms' answers
    ``{(floor, room): (on, attrs)}``: who is where, summed up for "anyone
    upstairs?" and "anyone home?" without naming every room."""
    floors: dict[str, dict] = {}
    for k in keys:
        on, attrs = (answers or {}).get((k["floor"], k["room"])) or (False, {})
        f = floors.setdefault(k["floor"], {"rooms": [], "people": set(), "pets": set(), "count": 0, "floor_id": k["floor_id"]})
        if on:
            f["rooms"].append(k["room"])
        f["people"].update(attrs.get("people") or [])
        f["pets"].update(attrs.get("pets") or [])
        f["count"] += attrs.get("count") or 0
    shaped = {name: (bool(f["rooms"]), {"floor": name, "floor_id": f["floor_id"], "rooms": f["rooms"], "people": sorted(f["people"]),
                                         "pets": sorted(f["pets"]), "count": f["count"]}) for name, f in floors.items()}
    people = sorted({p for _on, a in shaped.values() for p in a["people"]})
    pets = sorted({p for _on, a in shaped.values() for p in a["pets"]})
    rooms = [f"{a['floor']}: {r}" for _on, a in shaped.values() for r in a["rooms"]]
    return shaped, (bool(rooms), {"rooms": rooms, "people": people, "pets": pets,
                                  "count": sum(a["count"] for _on, a in shaped.values())})
