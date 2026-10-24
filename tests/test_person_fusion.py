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


def state(value, attrs=None, ago=60.0):
    """An HA State stand-in: state, attributes, last_updated/last_reported."""
    when = NOW_DT - timedelta(seconds=ago)
    return types.SimpleNamespace(state=value, attributes=attrs or {}, last_updated=when, last_reported=when)


GPS = {"latitude": 41.30, "longitude": -81.70, "gps_accuracy": 15, "source_type": "gps"}
LAYOUT = {"person_trackers": {"person.eilee": ["device_tracker.eilees_iphone", "device_tracker.eilee_bauer"]}}


# --- one source -------------------------------------------------------------

def test_a_fresh_gps_tracker_is_usable_with_its_zone_and_coordinates():
    ok, reason, info = persons.judge_source("device_tracker.t", state("Lawrence Upper School", GPS), NOW)
    assert ok and reason is None
    assert info["zone"] == "Lawrence Upper School" and info["latitude"] == 41.30 and info["accuracy"] == 15


def test_a_missing_or_unavailable_tracker_is_broken():
    assert persons.judge_source("device_tracker.t", None, NOW)[:2] == (False, "not found")
    assert persons.judge_source("device_tracker.t", state("unavailable", GPS), NOW)[:2] == (False, "unavailable")
    assert persons.judge_source("device_tracker.t", state("unknown"), NOW)[:2] == (False, "unknown")


def test_a_tracker_that_stopped_reporting_is_stale():
    """Eilee's Companion app: frozen on home for six days after losing its
    location permission. Six days without a report is not a location."""
    ok, reason, _ = persons.judge_source("device_tracker.t", state("home", GPS, ago=6 * 86400), NOW, stale_secs=7200)
    assert not ok and reason.startswith("no report for 144.0 h")


def test_a_zone_only_tracker_still_gives_its_zone():
    ok, _, info = persons.judge_source("device_tracker.t", state("Kent State Dorm"), NOW)
    assert ok and info["zone"] == "Kent State Dorm" and info["latitude"] is None


def test_an_icloud3_stationary_zone_is_not_home_with_the_coordinates_kept():
    """David parked 2 km from home for ten minutes: iCloud3 drew StatZon1
    round the phone and the Companion app, person and Sextant all said so.
    A polling device is not a place."""
    attrs = {**GPS, "in_zones": ["zone.ic3_stationary_1"]}
    ok, _, info = persons.judge_source("device_tracker.t", state("StatZon1", attrs), NOW)
    assert ok and info["zone"] == "not_home" and info["stationary"] is True
    assert info["latitude"] == 41.30 and info["accuracy"] == 15
    # Renamed in iCloud3 ("Parked#"): the zone's entity id still tells.
    renamed = persons.judge_source("device_tracker.t", state("Parked2", attrs), NOW)[2]
    assert renamed["zone"] == "not_home" and renamed["stationary"]
    # No in_zones (an older build): the default name is enough.
    assert persons.judge_source("device_tracker.t", state("StatZon3", GPS), NOW)[2]["zone"] == "not_home"
    # A real zone is untouched, whatever else is in the list.
    real = persons.judge_source("device_tracker.t", state("Kent State", {**GPS, "in_zones": ["zone.kent_state"]}), NOW)[2]
    assert real["zone"] == "Kent State" and real["stationary"] is False
    assert not persons.stationary_zone("Station", {})


# --- choosing among sources ---------------------------------------------------

def test_the_first_usable_source_wins_and_the_passed_over_are_named():
    states = {"device_tracker.eilees_iphone": state("home", GPS, ago=6 * 86400),
              "device_tracker.eilee_bauer": state("Lawrence Upper School", GPS)}
    chosen, ignored = persons.choose_gps(states.get, LAYOUT, "person.eilee", NOW)
    assert chosen["entity"] == "device_tracker.eilee_bauer"
    assert ignored == [{"entity": "device_tracker.eilees_iphone", "reason": "no report for 144.0 h"}]


def test_preference_order_is_honoured_when_both_are_usable():
    states = {"device_tracker.eilees_iphone": state("home", GPS), "device_tracker.eilee_bauer": state("not_home", GPS)}
    chosen, ignored = persons.choose_gps(states.get, LAYOUT, "person.eilee", NOW)
    assert chosen["entity"] == "device_tracker.eilees_iphone" and ignored == []


def test_no_sources_configured_means_nothing_chosen():
    assert persons.choose_gps(lambda e: None, {}, "person.eilee", NOW) == (None, [])


def test_a_person_is_as_present_as_their_most_present_thing():
    assert persons.presence_of_things(["away", "quiet", "here"]) == "here"
    assert persons.presence_of_things(["away", "quiet"]) == "quiet"
    assert persons.presence_of_things([]) == "away"


# --- the fused answer ---------------------------------------------------------

def _best():
    return {"ent": "watch", "cls": "watch", "updated": NOW - 5, "arrived": NOW - 600, "zone": "Eilee Room",
            "sub_zone": "unknown", "floor": "Second Floor", "area": ("eilee_room", "second_floor")}


def test_here_is_the_room_by_ble_with_gps_alongside():
    gps = {"entity": "device_tracker.eilee_bauer", "zone": "home", "latitude": 41.3001, "longitude": -81.7001, "accuracy": 10}
    out = persons.fuse(_best(), [], "here", None, gps, [], home=(41.30, -81.70))
    loc_state, loc = out["sextant_person_location"]
    assert loc_state == "Eilee Room" and loc["source"] == "ble" and loc["presence"] == "here"
    assert loc["zone"] == "home" and loc["tracker"] == "device_tracker.eilee_bauer" and 0 < loc["distance_m"] < 30
    assert out["sextant_person_room"][0] == "Eilee Room" and out["sextant_person_room"][1]["source"] == "ble"


def test_quiet_holds_the_last_place_they_were_put():
    out = persons.fuse(None, None, "quiet", _best(), None, [], home=None)
    loc_state, loc = out["sextant_person_location"]
    assert loc_state == "Eilee Room" and loc["source"] == "held" and loc["presence"] == "quiet"
    assert out["sextant_person_floor"][0] == "Second Floor"


def test_away_is_the_gps_zone_and_the_rooms_go_unknown():
    gps = {"entity": "device_tracker.eilee_bauer", "zone": "Lawrence Upper School", "latitude": 41.40, "longitude": -81.60, "accuracy": 20}
    out = persons.fuse(None, None, "away", None, gps, [{"entity": "device_tracker.eilees_iphone", "reason": "no report for 144.0 h"}], home=(41.30, -81.70))
    loc_state, loc = out["sextant_person_location"]
    assert loc_state == "Lawrence Upper School" and loc["source"] == "gps" and loc["kind"] == "zone"
    assert loc["distance_m"] > 10000 and loc["gps_ignored"][0]["entity"] == "device_tracker.eilees_iphone"
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

HOME = (41.30, -81.70)


def _fix(zone="not_home", lat=41.34, lon=-81.70, reported=NOW - 30, accuracy=15):
    return {"entity": "device_tracker.t", "zone": zone, "latitude": lat, "longitude": lon, "accuracy": accuracy, "reported": reported}


def test_a_fresh_fix_well_down_the_road_ends_the_hold():
    """David's drive: the house fell quiet at 12:53, the phone reported 5 km
    out at 12:55, and the card said Kitchen until 13:09. Not any more."""
    assert persons.gps_left(_fix(), NOW - 300, HOME)


def test_a_fix_from_before_the_last_sighting_says_nothing_about_now():
    assert not persons.gps_left(_fix(reported=NOW - 400), NOW - 300, HOME)
    assert not persons.gps_left(_fix(reported=None), NOW - 300, HOME)


def test_a_fix_in_the_home_zone_or_near_the_property_line_keeps_the_hold():
    assert not persons.gps_left(_fix(zone="home"), NOW - 300, HOME)
    assert not persons.gps_left(_fix(lat=41.3010), NOW - 300, HOME)              # ~110 m: GPS wandering
    assert not persons.gps_left(_fix(lat=41.3020, accuracy=100), NOW - 300, HOME)  # 220 m less 100 m of accuracy


def test_only_a_fix_with_coordinates_counts_and_zero_turns_it_off():
    assert not persons.gps_left(_fix(lat=None, lon=None), NOW - 300, HOME)
    assert not persons.gps_left(_fix(), NOW - 300, None)
    assert not persons.gps_left(_fix(), NOW - 300, HOME, 0)
    assert not persons.gps_left(None, NOW - 300, HOME)


def test_never_heard_still_lets_a_far_fix_speak():
    assert persons.gps_left(_fix(), None, HOME)


# --- the device_tracker's word ------------------------------------------------

def test_the_tracker_is_home_on_ble_and_gps_once_lost():
    gps = {"entity": "device_tracker.t", "zone": "Lawrence Upper School", "latitude": 41.4, "longitude": -81.6, "accuracy": 20}
    assert persons.tracker_fix("here", gps)["location_name"] == "home"
    assert persons.tracker_fix("quiet", None)["source_type"] == "bluetooth_le"
    fix = persons.tracker_fix("away", gps)
    assert fix["location_name"] is None and fix["latitude"] == 41.4 and fix["source_type"] == "gps"
    assert persons.tracker_fix("away", {"entity": "device_tracker.t", "zone": "Kent State Dorm", "latitude": None})["location_name"] == "Kent State Dorm"
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
    assert persons.home_via("away", {"entity": "device_tracker.t", "zone": "Kent State Dorm"}) is None
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
    run(ws.ws_person_trackers_set(hass, conn, {"id": 1, "type": "sextant/person/trackers/set", "person": "person.eilee",
                                              "trackers": ["device_tracker.b", "device_tracker.a", "device_tracker.b", "sensor.nope"]}))
    assert not conn.errors and conn.results[0][1]["trackers"] == ["device_tracker.b", "device_tracker.a"]
    assert st.get_layout(hass)["person_trackers"] == {"person.eilee": ["device_tracker.b", "device_tracker.a"]}
    run(ws.ws_person_trackers_set(hass, conn, {"id": 2, "type": "sextant/person/trackers/set", "person": "person.eilee", "trackers": []}))
    assert "person_trackers" not in st.get_layout(hass)
    run(ws.ws_person_trackers_set(hass, conn, {"id": 3, "type": "sextant/person/trackers/set", "person": "eilee", "trackers": []}))
    assert conn.errors
