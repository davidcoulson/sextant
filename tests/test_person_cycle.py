"""The person cycle over several cycles (_update_person_sensors): a GPS
departure that a later source saw first, the cycle that source drops out for,
and the return. The rule itself is tested in test_person_fusion (choose_gps);
this is the loop keeping its word from one cycle to the next."""
import asyncio
import time
import types
from datetime import datetime, timezone

import sextant
from sextant import sensor as sensor_mod, storage as st
from conftest import make_hass

PERSON, LOCATION = "person.robin", "sensor.robin_sextant_person_location"
APP, OTHER = "device_tracker.robins_iphone", "device_tracker.robin_smith"
KITCHEN = {"ent": "phone", "cls": "phone", "zone": "Kitchen", "sub_zone": "unknown", "floor": "Ground Floor",
           "area": ("kitchen", "ground_floor")}


def _tracker(value, lat, ago, changed_ago=None):
    def at(secs):
        return datetime.fromtimestamp(time.time() - secs, timezone.utc)
    return types.SimpleNamespace(state=value, attributes={"latitude": lat, "longitude": -0.10, "gps_accuracy": 15},
                                 last_updated=at(ago), last_reported=at(ago), last_changed=at(ago if changed_ago is None else changed_ago))


def test_a_departure_a_later_source_saw_stands_through_its_dropout_until_the_first_turns_home(tmp_path, monkeypatch):
    hass = make_hass(tmp_path)
    hass.config.latitude, hass.config.longitude = 51.50, -0.10
    asyncio.new_event_loop().run_until_complete(st.save_layout(hass, {
        "floor": [], "thing_owners": {"phone": PERSON}, "thing_classes": {"phone": "phone"},
        "person_trackers": {PERSON: [APP, OTHER]}, "tuning": {"person_log_hours": 0.0}}))
    states, written, heard = {}, {}, time.time() - 300
    hass.states = types.SimpleNamespace(get=lambda e: states.get(e))
    visits = {PERSON: {"arrived": heard - 9000, "departed": None, "via": "ble"}}
    for name, value in {
        "_last_seen": {"phone": {"updated": heard}},          # quiet: last heard five minutes ago
        "_person_last": {PERSON: (dict(KITCHEN, updated=heard, arrived=heard - 600), [])},
        "_person_visits": visits, "_event_visits": dict(visits), "_events_from": 0.0,
        "_gps_gone": {}, "_gps_asked": {}, "_person_sleep": {}, "_person_places": {}, "_person_log_key": {},
        "_wifi_since": {}, "_event_places": {}, "_place_pending": {}, "_wifi_now": {},
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

    # The phone app still says home; the other service has the car 4 km down the road.
    states.update({APP: _tracker("home", 51.50, 7200), OTHER: _tracker("not_home", 51.54, 30)})
    assert cycle() == ("away", "gps", OTHER, ["sextant_person_left", "sextant_everyone_left"])
    # The other service drops out for a cycle: no held Kitchen, no "home" from the app, no arrival.
    states[OTHER] = _tracker("unavailable", 51.54, 1)
    assert cycle() == ("away", "none", None, [])
    states[OTHER] = _tracker("not_home", 51.54, 40)
    assert cycle() == ("away", "gps", OTHER, [])
    # Coming back: the app turns home at the gate while the other still shows the road.
    states[APP] = _tracker("home", 51.50, 5)
    assert cycle() == ("home", "gps", APP, ["sextant_person_arrived", "sextant_first_arrived"])
    # Heard in the house: the departure is done with.
    sextant._last_seen["phone"] = {"updated": time.time() - 1}
    cycle()
    assert sextant._gps_gone[PERSON] is None
