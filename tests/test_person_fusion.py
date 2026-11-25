"""A person's location fused from BLE and GPS (persons.py: judge_source,
choose_gps, presence_of_things, fuse, tracker_fix), and the command that sets
their GPS sources."""
import asyncio
import types
from datetime import datetime, timedelta, timezone

from sextant import persons
from sextant import ws
from sextant import storage as st
from conftest import make_hass

NOW_DT = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)
NOW = NOW_DT.timestamp()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def state(value, attrs=None, ago=60.0, changed_ago=None, reported_ago=None):
    """An HA State stand-in: state, attributes, last_updated/last_reported, last_changed."""
    when = NOW_DT - timedelta(seconds=ago)
    return types.SimpleNamespace(state=value, attributes=attrs or {}, last_updated=when,
                                 last_reported=when if reported_ago is None else NOW_DT - timedelta(seconds=reported_ago),
                                 last_changed=NOW_DT - timedelta(seconds=ago if changed_ago is None else changed_ago))


GPS = {"latitude": 51.50, "longitude": -0.10, "gps_accuracy": 15, "source_type": "gps"}
LAYOUT = {"person_trackers": {"person.robin": ["device_tracker.robins_iphone", "device_tracker.robin_smith"]}}


# --- one source -------------------------------------------------------------

def test_a_fresh_gps_tracker_is_usable_with_its_zone_and_coordinates():
    ok, reason, info = persons.judge_source("device_tracker.t", state("Hill Academy", GPS), NOW)
    assert ok and reason is None
    assert info["zone"] == "Hill Academy" and info["latitude"] == 51.50 and info["accuracy"] == 15


def test_a_missing_or_unavailable_tracker_is_broken():
    assert persons.judge_source("device_tracker.t", None, NOW)[:2] == (False, "not found")
    assert persons.judge_source("device_tracker.t", state("unavailable", GPS), NOW)[:2] == (False, "unavailable")
    assert persons.judge_source("device_tracker.t", state("unknown"), NOW)[:2] == (False, "unknown")


def test_a_tracker_that_stopped_reporting_is_stale():
    """Robin's Companion app: frozen on home for six days after losing its
    location permission. Six days without a report is not a location."""
    ok, reason, _ = persons.judge_source("device_tracker.t", state("home", GPS, ago=6 * 86400), NOW, stale_secs=7200)
    assert not ok and reason.startswith("no report for 144.0 h")


def test_a_zone_only_tracker_still_gives_its_zone():
    ok, _, info = persons.judge_source("device_tracker.t", state("Hill College Dorm"), NOW)
    assert ok and info["zone"] == "Hill College Dorm" and info["latitude"] is None


def test_coordinates_off_the_globe_are_no_coordinates():
    """An infinite latitude would raise in the distance sum and stop everyone's update."""
    for bad in ({"latitude": float("inf")}, {"longitude": 181.0}, {"latitude": float("nan")}):
        ok, _, info = persons.judge_source("device_tracker.t", state("not_home", {**GPS, **bad}), NOW)
        assert ok and info["zone"] == "not_home" and info["latitude"] is None and info["longitude"] is None
        assert not persons.gps_left(info, NOW - 300, HOME)


def test_an_icloud3_stationary_zone_is_not_home_with_the_coordinates_kept():
    """Alex parked 2 km from home for ten minutes: iCloud3 drew StatZon1
    round the phone and the Companion app, person and Sextant all said so.
    A polling device is not a place."""
    attrs = {**GPS, "in_zones": ["zone.ic3_stationary_1"]}
    ok, _, info = persons.judge_source("device_tracker.t", state("StatZon1", attrs), NOW)
    assert ok and info["zone"] == "not_home" and info["stationary"] is True
    assert info["latitude"] == 51.50 and info["accuracy"] == 15
    # Renamed in iCloud3 ("Parked#"): the zone's entity id still tells.
    renamed = persons.judge_source("device_tracker.t", state("Parked2", attrs), NOW)[2]
    assert renamed["zone"] == "not_home" and renamed["stationary"]
    # No in_zones (an older build): the default name is enough.
    assert persons.judge_source("device_tracker.t", state("StatZon3", GPS), NOW)[2]["zone"] == "not_home"
    # A real zone is untouched, whatever else is in the list.
    real = persons.judge_source("device_tracker.t", state("Hill College", {**GPS, "in_zones": ["zone.hill_college"]}), NOW)[2]
    assert real["zone"] == "Hill College" and real["stationary"] is False
    assert not persons.stationary_zone("Station", {})


# --- choosing among sources ---------------------------------------------------

def test_the_usable_sources_keep_their_order_and_the_passed_over_are_named():
    states = {"device_tracker.robins_iphone": state("home", GPS, ago=6 * 86400),
              "device_tracker.robin_smith": state("Hill Academy", GPS)}
    usable, ignored = persons.usable_gps(states.get, LAYOUT, "person.robin", NOW)
    assert [g["entity"] for g in usable] == ["device_tracker.robin_smith"]
    assert ignored == [{"entity": "device_tracker.robins_iphone", "reason": "no report for 144.0 h"}]


def test_preference_order_is_honoured_when_both_are_usable():
    states = {"device_tracker.robins_iphone": state("home", GPS), "device_tracker.robin_smith": state("not_home", GPS)}
    usable, ignored = persons.usable_gps(states.get, LAYOUT, "person.robin", NOW)
    assert [g["entity"] for g in usable] == ["device_tracker.robins_iphone", "device_tracker.robin_smith"] and ignored == []
    # Heard a moment ago: the first one speaks, whatever another says.
    assert persons.choose_gps(usable, "here", NOW - 5, None, HOME) == (usable[0], None)


def test_no_sources_configured_means_nothing_chosen():
    assert persons.usable_gps(lambda e: None, {}, "person.robin", NOW) == ([], [])
    assert persons.choose_gps([], "away", None) == (None, None)


def test_a_source_tells_when_its_zone_and_its_fix_last_changed():
    """A report with nothing new in it moves only the report time."""
    info = persons.judge_source("device_tracker.t", state("home", GPS, ago=60, changed_ago=900, reported_ago=5), NOW)[2]
    assert (info["changed"], info["updated"], info["reported"]) == (NOW - 900, NOW - 60, NOW - 5)


def test_a_person_is_as_present_as_their_most_present_thing():
    assert persons.presence_of_things(["away", "quiet", "here"]) == "here"
    assert persons.presence_of_things(["away", "quiet"]) == "quiet"
    assert persons.presence_of_things([]) == "away"


# --- the fused answer ---------------------------------------------------------

def _best():
    return {"ent": "watch", "cls": "watch", "updated": NOW - 5, "arrived": NOW - 600, "zone": "Robin Room",
            "sub_zone": "unknown", "floor": "Second Floor", "area": ("robin_room", "second_floor")}


def test_here_is_the_room_by_ble_with_gps_alongside():
    gps = {"entity": "device_tracker.robin_smith", "zone": "home", "latitude": 51.5001, "longitude": -0.1001, "accuracy": 10}
    out = persons.fuse(_best(), [], "here", None, gps, [], home=(51.50, -0.10))
    loc_state, loc = out["sextant_person_location"]
    assert loc_state == "Robin Room" and loc["source"] == "ble" and loc["presence"] == "here"
    assert loc["zone"] == "home" and loc["tracker"] == "device_tracker.robin_smith" and 0 < loc["distance_m"] < 30
    assert out["sextant_person_room"][0] == "Robin Room" and out["sextant_person_room"][1]["source"] == "ble"


def test_quiet_holds_the_last_place_they_were_put():
    out = persons.fuse(None, None, "quiet", _best(), None, [], home=None)
    loc_state, loc = out["sextant_person_location"]
    assert loc_state == "Robin Room" and loc["source"] == "held" and loc["presence"] == "quiet"
    assert out["sextant_person_floor"][0] == "Second Floor"


def test_away_is_the_gps_zone_and_the_rooms_go_unknown():
    gps = {"entity": "device_tracker.robin_smith", "zone": "Hill Academy", "latitude": 51.60, "longitude": 0.00, "accuracy": 20}
    out = persons.fuse(None, None, "away", None, gps, [{"entity": "device_tracker.robins_iphone", "reason": "no report for 144.0 h"}], home=(51.50, -0.10))
    loc_state, loc = out["sextant_person_location"]
    assert loc_state == "Hill Academy" and loc["source"] == "gps" and loc["kind"] == "zone"
    assert loc["distance_m"] > 10000 and loc["gps_ignored"][0]["entity"] == "device_tracker.robins_iphone"
    assert out["sextant_person_room"] == ("unknown", {"area_id": None, "via": None, "source": "gps", "presence": "away"})


def test_away_with_gps_saying_not_home_reads_away():
    gps = {"entity": "device_tracker.t", "zone": "not_home", "latitude": 41.4, "longitude": -81.6, "accuracy": 5}
    assert persons.fuse(None, None, "away", None, gps, [])["sextant_person_location"][0] == "away"


def test_away_with_nothing_usable_says_so():
    loc_state, loc = persons.fuse(None, None, "away", None, None, [{"entity": "device_tracker.t", "reason": "unavailable"}])["sextant_person_location"]
    assert loc_state == "away" and loc["source"] == "none" and loc["latitude"] is None


def test_a_quiet_person_with_nothing_held_falls_through_to_gps():
    """Quiet only holds a place that was ever known; with none, GPS or away."""
    gps = {"entity": "device_tracker.t", "zone": "home", "latitude": 41.3, "longitude": -81.7, "accuracy": 5}
    assert persons.fuse(None, None, "quiet", None, gps, [])["sextant_person_location"][0] == "home"


# --- GPS ending the hold early --------------------------------------------------

HOME = (51.50, -0.10)


def _fix(zone="not_home", lat=51.54, lon=-0.10, reported=NOW - 30, accuracy=15):
    return {"entity": "device_tracker.t", "zone": zone, "latitude": lat, "longitude": lon, "accuracy": accuracy, "reported": reported}


def test_a_fresh_fix_well_down_the_road_ends_the_hold():
    """Alex's drive: the house fell quiet at 12:53, the phone reported 5 km
    out at 12:55, and the card said Kitchen until 13:09. Not any more."""
    assert persons.gps_left(_fix(), NOW - 300, HOME)


def test_a_fix_from_before_the_last_sighting_says_nothing_about_now():
    assert not persons.gps_left(_fix(reported=NOW - 400), NOW - 300, HOME)
    assert not persons.gps_left(_fix(reported=None), NOW - 300, HOME)


def test_a_fix_in_the_home_zone_or_near_the_property_line_keeps_the_hold():
    assert not persons.gps_left(_fix(zone="home"), NOW - 300, HOME)
    assert not persons.gps_left(_fix(lat=51.5010), NOW - 300, HOME)              # ~110 m: GPS wandering
    assert not persons.gps_left(_fix(lat=51.5020, accuracy=100), NOW - 300, HOME)  # 220 m less 100 m of accuracy


def test_only_a_fix_with_coordinates_counts_and_zero_turns_it_off():
    assert not persons.gps_left(_fix(lat=None, lon=None), NOW - 300, HOME)
    assert not persons.gps_left(_fix(), NOW - 300, None)
    assert not persons.gps_left(_fix(), NOW - 300, HOME, 0)
    assert not persons.gps_left(None, NOW - 300, HOME)


def test_never_heard_still_lets_a_far_fix_speak():
    assert persons.gps_left(_fix(), None, HOME)


# --- the device_tracker's word ------------------------------------------------

def test_the_tracker_is_home_on_ble_and_gps_once_lost():
    gps = {"entity": "device_tracker.t", "zone": "Hill Academy", "latitude": 41.4, "longitude": -81.6, "accuracy": 20}
    assert persons.tracker_fix("here", gps)["location_name"] == "home"
    assert persons.tracker_fix("quiet", None)["source_type"] == "bluetooth_le"
    fix = persons.tracker_fix("away", gps)
    assert fix["location_name"] is None and fix["latitude"] == 41.4 and fix["source_type"] == "gps"
    assert persons.tracker_fix("away", {"entity": "device_tracker.t", "zone": "Hill College Dorm", "latitude": None})["location_name"] == "Hill College Dorm"
    assert persons.tracker_fix("away", None)["location_name"] == "not_home"


def test_the_tracker_reads_not_home_in_a_stationary_zone_but_keeps_the_fix():
    """Coordinates alone would let Home Assistant name StatZon1 from them
    again, so the fix says not_home outright, coordinates beside it for the
    map card. The location sensor says away."""
    gps = {"entity": "device_tracker.t", "zone": "not_home", "stationary": True, "latitude": 41.312, "longitude": -81.731, "accuracy": 17}
    fix = persons.tracker_fix("away", gps)
    assert fix["location_name"] == "not_home" and fix["latitude"] == 41.312 and fix["source_type"] == "gps"
    assert persons.fuse(None, [], "away", None, gps, [])["sextant_person_location"][0] == "away"


def test_a_visit_starts_at_the_sighting_and_holds_while_home():
    v = persons.visit(None, "ble", 1000.0, 1010.0)
    assert v == {"arrived": 1000.0, "departed": None, "via": "ble"}
    assert persons.visit(v, "ble", 1200.0, 1210.0) is v            # same visit: nothing changes
    held = persons.visit(v, "gps", 1200.0, 1500.0)                 # BLE lost them, GPS still home: same visit
    assert held["arrived"] == 1000.0 and held["via"] == "gps"


def test_a_departure_is_stamped_at_the_last_sighting_not_the_timeout():
    v = {"arrived": 1000.0, "departed": None, "via": "ble"}
    gone = persons.visit(v, None, 2000.0, 2900.0)                # away_after_secs ran out at 2900
    assert gone == {"arrived": None, "departed": 2000.0}
    assert persons.visit(gone, None, 2000.0, 3600.0) is gone     # still away: the time stays
    back = persons.visit(gone, "ble", 5000.0, 5005.0)            # a new visit
    assert back == {"arrived": 5000.0, "departed": None, "via": "ble"}


def test_gps_driven_transitions_carry_gps_timing():
    """BLE silent since 08:00 (28800); GPS puts the phone in the home zone at
    18:00 (64800): the arrival is 18:00, not the morning's last sighting - and
    a departure GPS decides is stamped when GPS left, not at 08:00 either."""
    gone = {"arrived": None, "departed": 28800.0}
    home = persons.visit(gone, "gps", 28800.0, 64800.0)
    assert home == {"arrived": 64800.0, "departed": None, "via": "gps"}
    left = persons.visit(home, None, 28800.0, 72000.0)
    assert left == {"arrived": None, "departed": 72000.0}


def test_a_visit_with_no_sighting_falls_back_to_now_and_rubbish_is_ignored():
    assert persons.visit("nonsense", "ble", None, 42.0) == {"arrived": 42.0, "departed": None, "via": "ble"}
    assert persons.visit({}, None, None, 42.0) == {"arrived": None, "departed": 42.0}
    # Out-of-range, boolean, non-finite and float-overflowing times never reach datetime.
    assert persons.visit({"arrived": 1e20, "departed": None}, "ble", 1e20, 42.0) == {"arrived": 42.0, "departed": None, "via": "ble"}
    assert persons.visit_attrs({"arrived": 1e20, "departed": True}) == {"arrived_at": None, "departed_at": None}
    assert persons.visit_attrs({"arrived": float("nan"), "departed": None})["arrived_at"] is None
    assert persons.valid_time(10 ** 309) is None and persons.valid_time(True) is None and persons.valid_time(1700000000) == 1700000000.0


def test_the_visit_follows_the_tracker_not_ble_alone():
    """BLE lost them but GPS still has them in the home zone: the tracker says
    home, so no departure is stamped. Only once GPS leaves the zone too."""
    at_home_gps = {"entity": "device_tracker.t", "zone": "home", "latitude": 41.3, "longitude": -81.7}
    assert persons.home_via("away", at_home_gps) == "gps" and persons.tracker_home("away", at_home_gps) is True
    assert persons.home_via("away", {"entity": "device_tracker.t", "zone": "Hill College Dorm"}) is None
    assert persons.home_via("away", None) is None
    assert persons.home_via("quiet", None) == "ble"


def test_the_tracker_carries_exactly_one_of_arrived_or_departed():
    home = persons.tracker_fix("here", None, {"arrived": 1700000000.0, "departed": None, "via": "ble"})
    assert home["arrived_at"] == "2023-11-14T22:13:20+00:00" and home["departed_at"] is None
    away = persons.tracker_fix("away", None, {"arrived": None, "departed": 1700000000.0})
    assert away["departed_at"] == "2023-11-14T22:13:20+00:00" and away["arrived_at"] is None
    assert persons.tracker_fix("here", None)["arrived_at"] is None   # no visit known yet


# --- setting the sources ----------------------------------------------------

class _Conn:
    def __init__(self):
        self.results, self.errors = [], []

    def send_result(self, msg_id, result=None):
        self.results.append((msg_id, result))

    def send_error(self, msg_id, code, message):
        self.errors.append((msg_id, code, message))


def test_the_command_writes_the_order_and_clears_an_empty_list(tmp_path):
    hass = make_hass(tmp_path)
    run(st.save_layout(hass, {"floor": [{"name": "F", "scale": 100.0, "receivers": [], "zones": [], "subzones": []}]}))
    conn = _Conn()
    run(ws.ws_person_trackers_set(hass, conn, {"id": 1, "type": "sextant/person/trackers/set", "person": "person.robin",
                                              "trackers": ["device_tracker.b", "device_tracker.a", "device_tracker.b", "sensor.nope"]}))
    assert not conn.errors and conn.results[0][1]["trackers"] == ["device_tracker.b", "device_tracker.a"]
    assert st.get_layout(hass)["person_trackers"] == {"person.robin": ["device_tracker.b", "device_tracker.a"]}
    run(ws.ws_person_trackers_set(hass, conn, {"id": 2, "type": "sextant/person/trackers/set", "person": "person.robin", "trackers": []}))
    assert "person_trackers" not in st.get_layout(hass)
    run(ws.ws_person_trackers_set(hass, conn, {"id": 3, "type": "sextant/person/trackers/set", "person": "robin", "trackers": []}))
    assert conn.errors


# --- GPS over a Wi-Fi tracker that still reads home ------------------------------

def test_a_fix_down_the_road_after_the_router_last_saw_the_phone_overrules_wifi():
    """Sam's departures: Kitchen on Wi-Fi for up to 8 min with GPS 800 m out."""
    assert persons.wifi_outrun(_fix(), NOW - 200, HOME)
    # The router saw the watch leave half a minute before the fix: not the other way round.
    assert persons.wifi_outrun(_fix(), NOW - 50, HOME)


def test_a_watch_the_router_still_lists_but_stopped_hearing_is_overruled():
    """A departure held home 4 min by a watch: the router listed it until a
    minute before the fix, but had heard nothing from it for 289 s."""
    from sextant import wifi
    raw = {"last_seen": NOW - 20, "idletime": 289}        # last heard NOW - 309, before the fix at NOW - 30
    assert not persons.wifi_outrun(_fix(), raw["last_seen"], HOME)
    assert wifi.seen_for_gps(raw) == NOW - 309 and persons.wifi_outrun(_fix(), wifi.seen_for_gps(raw), HOME)
    # Quiet for under 90 s, as a watch on a desk often is: listed now, so a stray fix does not beat it.
    assert wifi.seen_for_gps({"last_seen": NOW - 2, "idletime": 89}) == NOW - 2
    assert not persons.wifi_outrun(_fix(), wifi.seen_for_gps({"last_seen": NOW - 2, "idletime": 89}), HOME)
    assert wifi.seen_for_gps({"last_seen": NOW - 2, "idletime": 90}) == NOW - 92
    assert wifi.seen_for_gps({"last_seen": NOW - 2}) == NOW - 2 and wifi.seen_for_gps(None) is None and wifi.seen_for_gps({"idletime": 300}) is None


def test_wifi_stands_on_an_arrival_or_without_a_last_seen_time():
    assert not persons.wifi_outrun(_fix(reported=NOW - 600), NOW - 5, HOME)   # home again: the old fix is the stale one
    assert not persons.wifi_outrun(_fix(), NOW - 35, HOME)                    # inside the margin
    assert not persons.wifi_outrun(_fix(), None, HOME)                        # not a UniFi client
    assert not persons.wifi_outrun(_fix(zone="home"), NOW - 200, HOME)


def test_heard_at_is_last_seen_less_idletime():
    """For the person log: the garage AP reported a watch 3 s ago that it had not heard for minutes."""
    from sextant import wifi
    assert wifi.heard_at({"last_seen": NOW - 3, "idletime": 150}) == NOW - 153
    assert wifi.heard_at({"last_seen": NOW - 3}) == NOW - 3              # no idletime: last_seen as before
    assert wifi.heard_at({"last_seen": NOW - 3, "idletime": -1}) == NOW - 3
    assert wifi.heard_at({"last_seen": NOW - 3, "idletime": True}) == NOW - 3
    assert wifi.heard_at({"last_seen": NOW - 3, "idletime": 85000, "uptime": 300}) == NOW - 3   # idle longer than associated: not seconds
    assert wifi.heard_at({"last_seen": NOW - 3, "idletime": 150, "uptime": 300}) == NOW - 153
    assert wifi.heard_at({"idletime": 5}) is None
    assert wifi.heard_at(None) is None


# --- Events ----------------------------------------------------------------------

D, M, J, CAT = "person.alex", "person.sam", "person.jamie", "person.meg"
IN = {"arrived": NOW - 3600, "departed": None, "via": "ble"}
OUT = {"arrived": None, "departed": NOW - 3600}


def _types(events):
    return [e for e, _ in events]


def test_a_departure_fires_left_and_the_last_one_everyone_left():
    """Jamie at the dorm all term never holds up "everyone left"."""
    gone = {"arrived": None, "departed": NOW - 60}
    one = persons.visit_events({D: IN, M: IN, J: OUT}, {D: gone, M: IN, J: OUT})
    assert one == [("sextant_person_left", {"person": D, "source": "ble", "time": persons.visit_attrs(gone)["departed_at"], "people_home": [M]})]
    both = persons.visit_events({D: gone, M: IN, J: OUT, CAT: IN}, {D: gone, M: gone, J: OUT, CAT: IN}, {CAT})
    assert _types(both) == ["sextant_person_left", "sextant_everyone_left"]
    assert both[1][1]["person"] == M


def test_an_arrival_fires_arrived_and_first_arrived_into_an_empty_house():
    back = {"arrived": NOW, "departed": None, "via": "gps"}
    events = persons.visit_events({D: OUT, M: OUT}, {D: back, M: OUT})
    assert _types(events) == ["sextant_person_arrived", "sextant_first_arrived"]
    assert events[0][1]["source"] == "gps" and events[0][1]["people_home"] == [D]
    assert _types(persons.visit_events({D: IN, M: OUT}, {D: IN, M: back})) == ["sextant_person_arrived"]


def test_no_event_for_a_state_merely_found_a_change_of_source_or_a_pet():
    assert persons.visit_events({}, {D: IN, M: OUT}) == []                    # first start
    assert persons.visit_events({D: IN}, {D: {**IN, "via": "wifi"}}) == []    # same visit, other source
    assert persons.visit_events({CAT: IN, D: OUT}, {CAT: OUT, D: OUT}, {CAT}) == []


def test_a_person_no_longer_tracked_does_not_count_as_having_been_home():
    back = {"arrived": NOW, "departed": None, "via": "ble"}
    assert _types(persons.visit_events({J: IN, D: OUT}, {D: back})) == ["sextant_person_arrived", "sextant_first_arrived"]


def test_a_restart_blip_between_two_tellings_makes_no_event():
    """Events compare the visits before the settle time with those after it:
    away and back in between is the same side, whatever the arrival time."""
    assert persons.visit_events({D: IN}, {D: {"arrived": NOW, "departed": None, "via": "gps"}}) == []


def test_a_watch_left_on_the_bedside_table_does_not_hold_the_person_home():
    """Eilee walked out with her phone at 11:05 and back at 11:29; the watch stayed
    on the bedside table, fresh in her room, and Sextant never noticed she had left."""
    watch = {"ent": "watch", "arrived": NOW - 40000}
    phone = {"ent": "phone", "arrived": NOW - 10}  # came to rest after the fix was made
    assert persons.without_left_behind([watch], _fix(), NOW, 120, HOME) == ([], [watch])
    assert persons.without_left_behind([watch, phone], _fix(), NOW, 120, HOME) == ([phone], [watch])
    # A fix in the home zone, or from before the watch came to rest, changes nothing.
    assert persons.without_left_behind([watch], _fix(zone="home"), NOW, 120, HOME) == ([watch], [])
    assert persons.without_left_behind([watch], _fix(reported=NOW - 50000), NOW, 120, HOME) == ([watch], [])
    assert persons.without_left_behind([watch], None, NOW, 120, HOME) == ([watch], [])


def test_a_thing_that_moved_recently_is_never_ruled_out_by_one_fix():
    walking = {"ent": "watch", "arrived": NOW - 60}
    assert persons.without_left_behind([walking], _fix(reported=NOW - 30), NOW, 120, HOME) == ([walking], [])


def test_a_phone_still_heard_at_home_means_gps_is_not_believed():
    """Both must agree: a fresh phone in the house keeps the watch, whatever one fix says."""
    watch = {"ent": "watch", "cls": "watch", "arrived": NOW - 40000, "updated": NOW}
    phone = {"ent": "phone", "cls": "phone", "arrived": NOW - 40000, "updated": NOW - 5}
    assert persons.without_left_behind([watch, phone], _fix(), NOW, 120, HOME) == ([watch, phone], [])
    phone["updated"] = NOW - 900  # not heard for 15 minutes: now they agree
    assert persons.without_left_behind([watch, phone], _fix(), NOW, 120, HOME) == ([], [watch, phone])


def test_a_wifi_word_must_stand_before_it_starts_a_visit():
    w = {"entity": "device_tracker.iphone", "home": True}
    away = {"arrived": None, "departed": 900.0}
    since, got = persons.wifi_gate(w, None, away, 1000.0, 300.0)
    assert (since, got) == (1000.0, None)                      # first sight: held back
    assert persons.wifi_gate(w, since, away, 1299.0, 300.0)[1] is None
    assert persons.wifi_gate(w, since, away, 1300.0, 300.0)[1] is w
    assert persons.wifi_gate(None, since, away, 1400.0, 300.0) == (None, None)   # a gap restarts the run
    assert persons.wifi_gate(w, None, away, 1000.0, 0.0)[1] is w                 # 0 = off


def test_a_visit_under_way_is_carried_on_by_wifi_at_once():
    w = {"entity": "device_tracker.iphone", "home": True}
    home = {"arrived": 500.0, "departed": None, "via": "ble"}
    assert persons.wifi_gate(w, None, home, 1000.0, 300.0)[1] is w
    assert persons.wifi_gate(w, None, None, 1000.0, 300.0)[1] is None            # no visit yet counts as away


def test_the_person_log_keeps_hours_and_drops_older(tmp_path):
    import os
    from sextant import person_log
    a, ka = person_log.row("jo", 1000.0, "wifi", "away", "home", True, {"ap": "x"}, {"ap": "x"}, 1200.4, "not_home", "Garage", best=None, things=[{"e": "p"}])
    c, kc = person_log.row("jo", 1030.0, "gps", "away", "away", False, None, None, 1230.0, "not_home")
    assert ka != kc and a["ble_age"] == 1200 and a["wifi_used"] is True and a["things"] == [{"e": "p"}]
    d = str(tmp_path / "log")
    person_log.append(d, [a, c], 48, now=1000.0)
    person_log.append(d, [a], 48, now=1000.0 + 47 * 3600)       # 47 h later: the first hour is still inside 48 h
    assert len(os.listdir(d)) == 2
    person_log.append(d, [c], 48, now=1000.0 + 49 * 3600)
    assert len(os.listdir(d)) == 2 and "1970-01-01T00Z.jsonl" not in os.listdir(d)


def test_a_room_change_is_a_change_in_the_person_log():
    from sextant import person_log
    _, a = person_log.row("jo", 1.0, "ble", "here", "Kitchen", True, None, None, 5, None)
    _, b = person_log.row("jo", 2.0, "ble", "here", "Bedroom", True, None, None, 5, None)
    assert a != b


# --- any source may mark the departure --------------------------------------------

HEARD = NOW - 300
APP_HOME = {"entity": "device_tracker.robins_iphone", "zone": "home", "latitude": 51.50, "longitude": -0.10,
            "accuracy": 15, "reported": NOW - 7200, "updated": NOW - 7200, "changed": NOW - 7200}
APP_BACK = {**APP_HOME, "reported": NOW - 20, "updated": NOW - 20, "changed": NOW - 20}


def _other(entity="device_tracker.robin_smith", **kw):
    fix = {**_fix(**kw), "entity": entity}
    return {**fix, "updated": fix["reported"]}


def _choose(usable, presence="quiet", heard=HEARD, gone_for=None, restored=0.0):
    return persons.choose_gps(usable, presence, heard, gone_for, HOME, 200.0, restored)


def test_a_later_source_that_has_seen_them_leave_speaks_while_the_first_still_says_home():
    """The phone app sat on "home" for two minutes into the drive; the other
    service had the car on the main road within one. The departure is kept
    against the sighting it followed."""
    far = _other(reported=NOW - 30)
    assert _choose([APP_HOME, far]) == (far, HEARD)
    assert _choose([APP_HOME, far], presence="away", heard=NOW - 3600) == (far, NOW - 3600)


def test_the_first_source_speaks_while_no_other_has_seen_them_leave():
    stale_news = {**_other(reported=NOW - 30), "updated": NOW - 400}   # reported again, the fix itself from before
    for other in (_other(zone="home"), _other(lat=51.5010), _other(reported=NOW - 400), stale_news):
        assert _choose([APP_HOME, other]) == (APP_HOME, None)
    assert _choose([APP_HOME]) == (APP_HOME, None)
    # Both have left: the person's order decides, as before.
    left = _other("device_tracker.robins_iphone")
    assert _choose([left, _other()]) == (left, HEARD)


def test_only_the_first_source_speaks_for_someone_heard_now_or_never_heard():
    """A watch at home is heard every few seconds, so there is no last
    sighting to hold a fix against; a visitor with no things has none either."""
    far = _other(reported=NOW - 1)
    assert _choose([APP_HOME, far], presence="here", heard=NOW - 2) == (APP_HOME, None)
    assert _choose([APP_HOME, far], presence="away", heard=None) == (APP_HOME, None)


def test_the_newest_of_several_fixes_down_the_road_speaks():
    older, newer = _other(reported=NOW - 200), _other("device_tracker.robin_tag", reported=NOW - 20)
    assert _choose([APP_HOME, older, newer])[0] is newer


def test_a_departure_once_seen_stands_until_they_are_heard_again():
    far = _other(reported=NOW - 30)
    gps, gone = _choose([APP_HOME, far])
    assert (gps, gone) == (far, HEARD)
    # The other service drops out for a cycle: the first one's old "home" does not call them back.
    assert _choose([APP_HOME], gone_for=gone) == (None, HEARD)
    assert _choose([], gone_for=gone) == (None, HEARD)
    assert _choose([APP_HOME, {**APP_HOME, "entity": "device_tracker.robin_tag"}], gone_for=gone) == (None, HEARD)
    # A nearer fix that no longer clears the guard is still theirs to tell: away, never the old "home".
    near = _other(lat=51.5012, reported=NOW - 5)
    assert _choose([APP_HOME, near], gone_for=gone) == (near, HEARD)
    # Coming back: the first source turns home at the gate while the other still shows the road.
    assert _choose([APP_BACK, far], gone_for=gone) == (APP_BACK, HEARD)
    assert _choose([APP_BACK, _other(reported=NOW - 10)], gone_for=gone) == (APP_BACK, HEARD)
    # Heard in the house: the spell is over, and so is its departure.
    assert _choose([APP_BACK, far], presence="here", heard=NOW - 1, gone_for=gone) == (APP_BACK, None)
    # A departure kept for another sighting is not this one's.
    assert _choose([APP_HOME], gone_for=HEARD - 900) == (APP_HOME, None)


def test_a_single_source_keeps_its_departure_through_a_dropout_too():
    left = _other("device_tracker.robins_iphone")
    assert _choose([left]) == (left, HEARD)
    assert _choose([], gone_for=HEARD) == (None, HEARD)


def test_a_home_restored_by_a_restart_is_no_arrival():
    """A restart stamps every restored state as just changed: the first
    source's "home" then looks like a return, and the other's old fix new."""
    heard, started = NOW - 600, NOW - 400
    restored_home = {**APP_HOME, "reported": started, "updated": started, "changed": started}
    far = _other(reported=NOW - 30)
    assert _choose([restored_home, far], heard=heard, restored=started + 300) == (far, heard)
    # A fix restored with it is no news either: the first source speaks, as it always did.
    assert _choose([restored_home, _other(reported=started)], heard=heard, restored=started + 300) == (restored_home, None)
