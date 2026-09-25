"""presence / last_heard on every per-thing sensor.

here while heard within stale_after_secs, quiet until away_after_secs, away
after that - the Live page's own three states, so an automation can read
home/away off a sensor and fall back to GPS when it says away.
"""
import time

import sextant
from sextant import storage as st
from conftest import make_hass

LAYOUT = {"floor": [], "tuning": {"stale_after_secs": 120.0, "away_after_secs": 900.0}}


def test_the_three_states_from_age():
    now = 1_000_000.0
    assert sextant._presence_of(now - 10, now, LAYOUT) == "here"
    assert sextant._presence_of(now - 120, now, LAYOUT) == "here"
    assert sextant._presence_of(now - 121, now, LAYOUT) == "quiet"
    assert sextant._presence_of(now - 900, now, LAYOUT) == "quiet"
    assert sextant._presence_of(now - 901, now, LAYOUT) == "away"
    assert sextant._presence_of(None, now, LAYOUT) == "away", "never heard is away"


def test_last_heard_is_an_iso_timestamp_or_none():
    a = sextant._presence_attrs(1_790_000_000, 1_790_000_005, LAYOUT)
    assert a["presence"] == "here" and a["last_heard"].startswith("2026-09-")
    assert sextant._presence_attrs(None, 1.0, LAYOUT) == {"presence": "away", "last_heard": None}


class _Sensor:
    def __init__(self, state, attrs):
        self._state, self._attrs, self.hass = state, attrs, None


def _hass_with_sensors(ent):
    hass = make_hass()
    hass.data["sextant_sensors"] = {
        f"sensor.{ent}{s}": _Sensor("Office", {"kind": "room"}) for s in sextant.THING_SENSOR_SUFFIXES
    }
    return hass


def test_a_thing_that_goes_quiet_gets_the_transition_written_once(monkeypatch):
    ent = "thing"
    hass = _hass_with_sensors(ent)
    sextant._last_seen.clear(); sextant._presence_published.clear()
    now = time.time()
    sextant._last_seen[ent] = {"updated": now - 300}
    calls = []
    orig = sextant.update_sextant_sensor_state
    monkeypatch.setattr(sextant, "update_sextant_sensor_state", lambda h, e, s, a=None: (calls.append(e), orig(h, e, s, a)))
    sextant._publish_presence(hass, LAYOUT)
    assert len(calls) == len(sextant.THING_SENSOR_SUFFIXES)
    loc = hass.data["sextant_sensors"][f"sensor.{ent}_sextant_location"]
    assert loc._attrs["presence"] == "quiet" and loc._attrs["kind"] == "room", "other attributes kept"
    assert loc._state == "Office", "the state is untouched: it is still the last known place"
    calls.clear()
    sextant._publish_presence(hass, LAYOUT)
    assert calls == [], "the same presence is not written again every cycle"
    sextant._last_seen[ent] = {"updated": now - 2000}
    sextant._publish_presence(hass, LAYOUT)
    assert loc._attrs["presence"] == "away"


def test_a_thing_still_heard_is_left_to_its_own_cycle():
    ent = "thing"
    hass = _hass_with_sensors(ent)
    sextant._last_seen.clear(); sextant._presence_published.clear()
    sextant._last_seen[ent] = {"updated": time.time() - 5}
    sextant._publish_presence(hass, LAYOUT)
    assert "presence" not in hass.data["sextant_sensors"][f"sensor.{ent}_sextant_location"]._attrs


def test_a_thing_with_sensors_but_no_remembered_sighting_is_away():
    """Jack's phone: not heard since before the sightings were first kept, so
    it has no entry - and its sensors must still say away, once."""
    ent = "never_heard"
    hass = _hass_with_sensors(ent)
    sextant._last_seen.clear(); sextant._presence_published.clear()
    sextant._publish_presence(hass, LAYOUT)
    loc = hass.data["sextant_sensors"][f"sensor.{ent}_sextant_location"]
    assert loc._attrs["presence"] == "away" and loc._attrs["last_heard"] is None
    assert sextant._presence_published[ent] == "away"


def test_forgetting_clears_the_published_presence():
    sextant._presence_published["gone"] = "away"
    sextant._forget_thing_state("gone")
    assert "gone" not in sextant._presence_published


def test_last_heard_is_not_recorded_but_presence_is():
    from sextant import sensor as sensor_mod
    assert "last_heard" in sensor_mod.CustomDistanceSensor._unrecorded_attributes
    assert "presence" not in sensor_mod.CustomDistanceSensor._unrecorded_attributes
