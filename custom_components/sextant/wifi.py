"""Wi-Fi association as a third source for people: BLE, then "the phone is
still joined to a home access point, so they are home", then GPS.

Home Assistant's UniFi Network integration (and any router integration that
sets ``ap_mac``) gives a device_tracker per Wi-Fi client with the access
point it is associated to. Sextant does not need to be told which tracker
is whose phone, nor where each access point reaches: it learns both from
its own BLE truth. Every cycle a person is placed by BLE, the access point
their phone is on gets that floor and room added to its footprint, and
every candidate tracker is scored against every person by how often its
access point's footprint agrees with where that person is. A tracker that
agrees with one person far more than with anyone else is suggested as
theirs (the People card shows it; a manual pick wins). The footprint is
what the floor election uses as a hint, so an access point that reaches
two floors - a wall unit under a bedroom - hints weakly, as it should.

Pure: no Home Assistant imports. __init__ does the registry lookups.
"""
from __future__ import annotations

import re

ROUTER = "router"
# Footprint counts are capped: halved when the cap is reached, so the
# distribution follows the house as proxies and furniture move.
FOOTPRINT_CAP = 4000.0
# A footprint is trusted once it has this many cycles; below that the access
# point's own area stands in (one floor, p = 1).
FOOTPRINT_MIN = 40
# A suggestion needs this many scored cycles and this much lead over the
# runner-up, as a share of agreement.
MATCH_MIN_CYCLES = 60
MATCH_MIN_LEAD = 0.2
# A tracker/person pair not scored for this long is forgotten, and the
# table never holds more than this many pairs (oldest out): phones and
# people turn over, the snapshot must not grow with their history.
MATCH_RETENTION_S = 30 * 86400
MATCH_MAX_PAIRS = 400


def new_store() -> dict:
    return {"aps": {}, "matches": {}}


def candidates(states, ap_macs=()) -> dict:
    """{tracker entity: {"name", "home", "ap", "mac"}} for every router
    tracker that carries an access-point attribute - a Wi-Fi client. The
    access points and switches themselves are router trackers too (UniFi
    tracks its own devices); they are told apart by their MAC being one of
    ``ap_macs``, or by never having been associated to anything.
    """
    out = {}
    aps = {str(m).lower() for m in ap_macs if m}
    for entity_id, state, attrs in states:
        if not str(entity_id).startswith("device_tracker.") or not isinstance(attrs, dict):
            continue
        if attrs.get("source_type") != ROUTER or "ap_mac" not in attrs:
            continue
        mac = str(attrs.get("mac") or "").lower()
        if mac and mac in aps:
            continue
        ap = attrs.get("ap_mac")
        out[entity_id] = {
            "name": attrs.get("friendly_name") or entity_id,
            "home": state == "home",
            "ap": str(ap).lower() if ap else None,
            "mac": mac or None,
            "ssid": attrs.get("essid") or None,
        }
    # The same client twice (a stale registry entry the integration reclaimed
    # beside the live one): keep the one that knows its access point, and
    # the better name of the two - "David's Phone" over "iPhone iPhone".
    by_mac: dict = {}
    for entity_id, c in out.items():
        if c["mac"]:
            cur = by_mac.get(c["mac"])
            if cur is None or (out[cur]["ap"] is None and c["ap"] is not None):
                by_mac[c["mac"]] = entity_id
    for entity_id, c in out.items():
        kept = by_mac.get(c["mac"]) if c["mac"] else None
        if kept and kept != entity_id:
            out[kept]["name"] = better_name(out[kept]["name"], c["name"])
    keep = set(by_mac.values()) | {e for e, c in out.items() if not c["mac"]}
    return {e: tidy(c) for e, c in out.items() if e in keep}


def _collapse(name: str) -> str:
    """"iPhone iPhone" -> "iPhone": the integration joins a device name and an
    entity name that are the same word."""
    words, seen = [], set()
    for w in str(name or "").split():
        if w.lower() not in seen:
            words.append(w)
            seen.add(w.lower())
    return " ".join(words)


def better_name(a: str, b: str) -> str:
    """The more telling of two names for one client: the longer once repeats
    are collapsed, so a name someone typed beats the model."""
    ca, cb = _collapse(a), _collapse(b)
    return cb if len(cb) > len(ca) else ca


def tidy(c: dict) -> dict:
    return {**c, "name": _collapse(c.get("name") or "")}


def _bump(counts: dict, key, cap=FOOTPRINT_CAP):
    counts[key] = counts.get(key, 0.0) + 1.0
    if sum(counts.values()) > cap:
        for k in list(counts):
            counts[k] = counts[k] / 2.0
            if counts[k] < 0.5:
                del counts[k]


def footprint_update(store: dict, ap: str, floor, room) -> None:
    """One BLE-placed cycle of a phone on ``ap``: its floor and room join the footprint."""
    if not ap or not floor:
        return
    fp = store.setdefault("aps", {}).setdefault(ap, {"floors": {}, "rooms": {}})
    _bump(fp["floors"], floor)
    if room and room != "unknown":
        _bump(fp["rooms"], room)


def floor_odds(store: dict, ap, fallback_floor=None) -> dict | None:
    """{floor: share} for an access point, from its footprint once that has
    FOOTPRINT_MIN cycles; else the access point's own floor at 1.0; else None."""
    fp = (store.get("aps") or {}).get(ap) if ap else None
    floors = (fp or {}).get("floors") or {}
    total = sum(floors.values())
    if total >= FOOTPRINT_MIN:
        return {f: n / total for f, n in floors.items()}
    return {fallback_floor: 1.0} if fallback_floor else None


def best_place(store: dict, ap, fallback=(None, None)) -> tuple:
    """(floor, room) an access point most often means, from its footprint
    once trusted; else the access point's own (floor, room); else (None, None)."""
    fp = (store.get("aps") or {}).get(ap) if ap else None
    floors = (fp or {}).get("floors") or {}
    if sum(floors.values()) >= FOOTPRINT_MIN:
        floor = max(floors, key=floors.get)
        rooms = (fp or {}).get("rooms") or {}
        return floor, (max(rooms, key=rooms.get) if rooms else None)
    return tuple(fallback) if fallback else (None, None)


def floor_factor(odds: dict | None, floor, weight: float) -> float:
    """The multiplier a floor's election score gets from the Wi-Fi hint:
    1 for the floor the access point most means, down to 1 - weight for a
    floor it never does. No odds, no change."""
    if not odds or weight <= 0:
        return 1.0
    p = odds.get(floor, 0.0)
    top = max(odds.values()) or 1.0
    return 1.0 - weight * (1.0 - p / top)


def agreement(tracker_home: bool, person_home: bool, same_floor) -> float:
    """How well one cycle of a tracker fits one person, 0..1.

    Both away, or both home and on the same floor: 1. Both home but the
    access point's floor is not the person's: 0.5 - a wall unit under a
    bedroom is still that bedroom's phone. One home and the other away: 0,
    the cycle that tells people apart. ``same_floor`` None (no floor known
    for the access point yet) counts as agreeing.
    """
    if tracker_home != person_home:
        return 0.0
    if not tracker_home:
        return 1.0
    return 1.0 if same_floor is None or same_floor else 0.5


def match_update(store: dict, tracker: str, person: str, agree, now=None) -> None:
    """Score one cycle of one candidate tracker against one person (agreement)."""
    m = store.setdefault("matches", {}).setdefault(tracker, {}).setdefault(person, {"agree": 0.0, "cycles": 0.0})
    m["cycles"] = float(m.get("cycles") or 0.0) + 1.0
    m["agree"] = float(m.get("agree") or 0.0) + float(agree)
    if now is not None:
        m["seen"] = float(now)
    if m["cycles"] > FOOTPRINT_CAP:
        m["cycles"] /= 2.0
        m["agree"] /= 2.0


def prune_matches(store: dict, now, max_age=MATCH_RETENTION_S, max_pairs=MATCH_MAX_PAIRS) -> int:
    """Forget tracker/person pairs not scored for ``max_age``, and the oldest
    beyond ``max_pairs``. A pair without a ``seen`` time is given one now, so
    an old store ages out from here rather than at once. Returns how many went."""
    matches = store.get("matches") or {}
    pairs = []
    for tracker, people in list(matches.items()):
        if not isinstance(people, dict):
            del matches[tracker]
            continue
        for person, m in list(people.items()):
            if not isinstance(m, dict):
                del people[person]
                continue
            seen = m.get("seen")
            if not isinstance(seen, (int, float)):
                m["seen"] = seen = float(now)
            pairs.append((seen, tracker, person))
    gone = 0
    doomed = [(t, p) for seen, t, p in pairs if now - seen > max_age]
    if len(pairs) - len(doomed) > max_pairs:
        keep = sorted((x for x in pairs if (x[1], x[2]) not in set(doomed)), reverse=True)[max_pairs:]
        doomed += [(t, p) for _s, t, p in keep]
    for tracker, person in doomed:
        if tracker in matches and person in matches[tracker]:
            del matches[tracker][person]
            gone += 1
    for tracker in [t for t, people in matches.items() if not people]:
        del matches[tracker]
    return gone


def suggest(store: dict, tracker: str, names: dict | None = None) -> tuple:
    """(person, confidence 0..1, why) for a tracker, or (None, 0, why).

    A tracker whose name contains a person's first name is theirs ("David's
    Phone" → person.david_coulson): confidence 1. Otherwise the person it
    agrees with most, once MATCH_MIN_CYCLES have been scored and the lead
    over the runner-up is MATCH_MIN_LEAD or more.
    """
    names = names or {}
    tname = str((store.get("names") or {}).get(tracker) or "").lower()
    # Whole words only - "Ian" must not claim "Brian's iPad" - and one
    # person only: two Davids leave the name out of it.
    words = set(re.findall(r"[a-z0-9]+", tname.replace("'s", "").replace("\u2019s", "")))
    named = [person for person, pname in names.items()
             if len(first := str(pname or "").split(" ")[0].lower()) > 2 and first in words]
    if len(named) == 1:
        return named[0], 1.0, "name"
    scores = (store.get("matches") or {}).get(tracker) or {}
    ranked = sorted(((m["agree"] / m["cycles"], m["cycles"], p) for p, m in scores.items() if m.get("cycles")), reverse=True)
    if not ranked or ranked[0][1] < MATCH_MIN_CYCLES:
        return None, 0.0, "learning"
    lead = ranked[0][0] - (ranked[1][0] if len(ranked) > 1 else 0.0)
    if lead < MATCH_MIN_LEAD:
        return None, round(ranked[0][0], 2), "ambiguous"
    return ranked[0][2], round(min(1.0, lead / (2 * MATCH_MIN_LEAD)), 2), "co-location"


def assignments(store: dict, trackers, people_names: dict, manual: dict | None = None) -> dict:
    """{person: {"entity", "how": "manual"|"name"|"co-location", "confidence"}}
    - the manual table first, then one suggestion per tracker, each person
    taking at most one tracker (the most confident)."""
    out = {}
    for person, entity in (manual or {}).items():
        if isinstance(entity, str) and entity:
            out[person] = {"entity": entity, "how": "manual", "confidence": 1.0}
    taken = {v["entity"] for v in out.values()}
    for tracker in trackers:
        if tracker in taken:
            continue
        person, conf, why = suggest(store, tracker, people_names)
        if person is None or person in out:
            continue
        cur = out.get(person)
        if cur is None or conf > cur["confidence"]:
            out[person] = {"entity": tracker, "how": why, "confidence": conf}
    return out
