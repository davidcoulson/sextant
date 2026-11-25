"""The person cycle over several cycles (_update_person_sensors): a GPS
departure that a later source saw first, the cycles its sources drop out for,
the return, and a second trip before Bluetooth hears them again. The rules
themselves are tested in test_person_fusion (usable_gps, choose_gps); this is
the loop reading them the same from one cycle to the next."""
import asyncio
import time
import types
from datetime import datetime, timezone

import sextant
from sextant import sensor as sensor_mod, storage as st
from conftest import make_hass

PERSON, LOCATION = "person.robin", "sensor.robin_sextant_person_location"
APP, OTHER, ROUTER = "device_tracker.robins_iphone", "device_tracker.robin_smith", "device_tracker.robins_iphone_wifi"
KITCHEN = {"ent": "phone", "cls": "phone", "zone": "Kitchen", "sub_zone": "unknown", "floor": "Ground Floor",
           "area": ("kitchen", "ground_floor")}
LEFT, ARRIVED = ["sextant_person_left", "sextant_everyone_left"], ["sextant_person_arrived", "sextant_first_arrived"]


def _tracker(value, lat, ago):
    when = datetime.fromtimestamp(time.time() - ago, timezone.utc)
    return types.SimpleNamespace(state=value, attributes={"latitude": lat, "longitude": -0.10, "gps_accuracy": 15},
                                 last_updated=when, last_reported=when, last_changed=when)


def _house(tmp_path, monkeypatch, tuning=None, wifi_view=None, wifi_clients=None):
    """A house with one person, last heard in the Kitchen five minutes ago
    (quiet, the room held): ``(states, cycle)``, cycle() running the person
    cycle and returning (state, source, tracker, the events fired)."""
    hass = make_hass(tmp_path)
    hass.config.latitude, hass.config.longitude = 51.50, -0.10
    asyncio.new_event_loop().run_until_complete(st.save_layout(hass, {
        "floor": [], "thing_owners": {"phone": PERSON}, "thing_classes": {"phone": "phone"},
        "person_trackers": {PERSON: [APP, OTHER]}, "tuning": {"person_log_hours": 0.0, **(tuning or {})}}))
    states, written, heard = {}, {}, time.time() - 300
    hass.states = types.SimpleNamespace(get=lambda e: states.get(e))
    visits = {PERSON: {"arrived": heard - 9000, "departed": None, "via": "ble"}}
    for name, value in {
        "_last_seen": {"phone": {"updated": heard}},
        "_person_last": {PERSON: (dict(KITCHEN, updated=heard, arrived=heard - 600), [])},
        "_person_visits": visits, "_event_visits": dict(visits), "_events_from": 0.0,
        "_gps_fixes": {}, "_gps_asked": {}, "_person_sleep": {}, "_person_places": {}, "_person_log_key": {},
        "_wifi_since": {}, "_event_places": {}, "_place_pending": {}, "_wifi_now": {}, "_wifi_store": {},
        "_wifi_cycle": lambda *a: dict(wifi_view or {}), "_unifi_clients": lambda h: wifi_clients or {},
        "update_sextant_sensor_state": lambda h, e, s, a=None: written.__setitem__(e, (s, a)),
        "_ask_phones_for_location": lambda *a: False,
    }.items():
        monkeypatch.setattr(sextant, name, value)
    monkeypatch.setattr(sensor_mod, "prune_person_sensors", lambda *a: None)
    monkeypatch.setattr(sensor_mod, "ensure_person_sensors", lambda *a: None)

    def cycle():
        hass.events.clear()
        sextant._update_person_sensors(hass)
        state, attrs = written[LOCATION]
        return state, attrs["source"], attrs["tracker"], [name for name, _ in hass.events]

    return states, cycle


def test_a_departure_a_later_source_saw_stands_through_dropouts_until_a_newer_home_fix(tmp_path, monkeypatch):
    states, cycle = _house(tmp_path, monkeypatch)
    # Both sources say home and both are usable: the Kitchen is held, as with no GPS at all.
    states.update({APP: _tracker("home", 51.50, 60), OTHER: _tracker("home", 51.50, 90)})
    held = cycle()
    assert held[0] == "Kitchen" and held[3] == []
    # The phone app still says home; the other service has the car 4 km down the road.
    states[OTHER] = _tracker("not_home", 51.54, 30)
    assert cycle() == ("away", "gps", OTHER, LEFT)
    # The other service drops out for a cycle: its fix stands. No held Kitchen, no "home" from the app, no arrival.
    states[OTHER] = _tracker("unavailable", 51.54, 1)
    assert cycle() == ("away", "gps", OTHER, [])
    # The app drops out too, and comes back with the fix it had: Home Assistant stamps it as changed, but it is no news.
    states[APP] = _tracker("unavailable", 51.50, 1)
    assert cycle() == ("away", "gps", OTHER, [])
    states.update({APP: _tracker("home", 51.50, 1), OTHER: _tracker("not_home", 51.54, 40)})
    assert cycle() == ("away", "gps", OTHER, [])
    # Coming back: the app has a new fix at the gate while the other still shows the road.
    # The Kitchen is held again until Bluetooth places them, as it is with one source.
    states[APP] = _tracker("home", 51.5001, 5)
    assert cycle() == (*held[:3], ARRIVED)
    assert cycle() == (*held[:3], [])
    # Out again before Bluetooth has heard them: the other service's newer fix down the road.
    states[OTHER] = _tracker("not_home", 51.56, 2)
    assert cycle() == ("away", "gps", OTHER, LEFT)


def test_a_return_only_the_second_source_has_seen_is_read(tmp_path, monkeypatch):
    states, cycle = _house(tmp_path, monkeypatch)
    states.update({APP: _tracker("home", 51.50, 60), OTHER: _tracker("home", 51.50, 90)})
    cycle()
    states[APP] = _tracker("not_home", 51.54, 30)
    assert cycle() == ("away", "gps", APP, LEFT)
    # Back at the gate by the other service's newer fix; the app still shows the road.
    states[OTHER] = _tracker("home", 51.5001, 5)
    assert cycle() == ("Kitchen", "held", OTHER, ARRIVED)
    assert cycle() == ("Kitchen", "held", OTHER, [])


def test_a_router_still_listing_the_phone_does_not_read_them_home_while_the_gps_source_is_out(tmp_path, monkeypatch):
    seen = time.time() - 200          # the access point last saw the phone before the fix down the road
    states, cycle = _house(
        tmp_path, monkeypatch, tuning={"wifi_confirm_secs": 0.0},
        wifi_view={"assigned": {PERSON: [{"entity": ROUTER}]}, "candidates": {ROUTER: {"home": True, "ap": "ap1", "mac": "aa"}},
                   "aps": {"ap1": {"name": "Hall", "floor": "Ground Floor", "room": "Kitchen"}}},
        wifi_clients={"aa": {"last_seen": seen}})
    states.update({APP: _tracker("home", 51.50, 60), OTHER: _tracker("home", 51.50, 90)})
    cycle()
    states[OTHER] = _tracker("not_home", 51.54, 30)
    assert cycle() == ("away", "gps", OTHER, LEFT)
    states[OTHER] = _tracker("unavailable", 51.54, 1)
    assert cycle() == ("away", "gps", OTHER, [])


def test_one_source_dropping_out_changes_nothing_and_a_stray_fix_corrected_gives_the_held_room_back(tmp_path, monkeypatch):
    """A tracker that goes unavailable has said nothing new: gone stays gone,
    and a fix corrected to the house stays corrected, with no second departure."""
    states, cycle = _house(tmp_path, monkeypatch)
    states[APP] = _tracker("home", 51.50, 60)
    held = cycle()
    states[APP] = _tracker("not_home", 51.54, 30)
    assert cycle() == ("away", "gps", APP, LEFT)
    states[APP] = _tracker("unavailable", 51.54, 1)
    assert cycle() == ("away", "gps", APP, [])
    states[APP] = _tracker("not_home", 51.5003, 2)          # 30 m from the house, not in the zone
    assert cycle() == (*held[:3], ARRIVED)
    states[APP] = _tracker("unavailable", 51.5003, 1)
    assert cycle() == (*held[:2], None, [])
    states[APP] = _tracker("not_home", 51.5003, 1)
    assert cycle() == (*held[:3], [])


def test_a_source_that_drops_out_while_it_says_home_keeps_nobody_home(tmp_path, monkeypatch):
    """A collar with a flat battery: its "home" is from before they were last
    heard, so with nothing heard for away_after_secs they are away, as with no GPS."""
    states, cycle = _house(tmp_path, monkeypatch, tuning={"away_after_secs": 120.0})
    states[APP] = _tracker("home", 51.50, 60)
    assert cycle()[1:3] == ("gps", APP)
    states[APP] = _tracker("unavailable", 51.50, 1)
    assert cycle() == ("away", "none", None, LEFT)
