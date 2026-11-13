"""A repair for a thing that looks dead: silent for a day with a flat battery.

Silence alone raises nothing (a tag at the kennel, a phone on holiday), and
the repair goes as soon as the thing is heard again or forgotten.
"""
import json
import time
import types
from pathlib import Path

import sextant
from conftest import make_hass

LAYOUT = {"thing_battery_entity": {"primrose": "sensor.primrose_battery"}, "thing_names": {"primrose": "Primrose"}}
KEY = ("sextant", "dead_thing_primrose")


def _hass(battery):
    hass = make_hass()
    states = {"sensor.primrose_battery": types.SimpleNamespace(state=battery)}
    hass.states = types.SimpleNamespace(get=states.get)
    return hass


def _heard(hours_ago):
    sextant._last_seen.clear()
    sextant._last_seen["primrose"] = {"zone": "Foyer", "floor": "Ground Floor", "updated": time.time() - hours_ago * 3600}


def test_raised_once_silent_for_a_day_with_a_flat_battery_and_cleared_when_heard():
    hass = _hass("1.0")
    _heard(85)
    sextant._update_dead_issues(hass, LAYOUT)
    issue = hass.data["issues"][KEY]
    assert issue["translation_placeholders"] == {"name": "Primrose", "age": "3 days", "where": "Foyer, Ground Floor", "battery": "1"}
    sextant._update_dead_issues(hass, LAYOUT)
    assert list(hass.data["issues"]) == [KEY], "the same id every cycle: never a second repair"
    _heard(0)
    sextant._update_dead_issues(hass, LAYOUT)
    assert not hass.data["issues"], "heard again: the repair is gone"


def test_not_raised_for_a_thing_that_is_only_away_or_only_low():
    for battery, hours in (("80", 85), ("unavailable", 85), ("1.0", 5)):
        hass = _hass(battery)
        _heard(hours)
        sextant._update_dead_issues(hass, LAYOUT)
        assert not hass.data.get("issues"), (battery, hours)
    # No battery sensor at all: a phone or a suitcase gone for days is away, not dead.
    hass = _hass("1.0")
    _heard(85)
    sextant._update_dead_issues(hass, {})
    assert not hass.data.get("issues")


def test_cleared_when_the_thing_is_forgotten():
    hass = _hass("1.0")
    _heard(85)
    sextant._update_dead_issues(hass, LAYOUT)
    assert KEY in hass.data["issues"]
    sextant._forget_thing_state("primrose")
    sextant._update_dead_issues(hass, LAYOUT)
    assert not hass.data["issues"]


def test_the_repair_has_its_text():
    en = json.loads((Path(sextant.__file__).parent / "translations" / "en.json").read_text())
    text = en["issues"]["dead_thing"]
    for key in ("name", "age", "where", "battery"):
        assert "{" + key + "}" in text["description"]
