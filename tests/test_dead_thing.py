"""A repair for a thing that looks dead: gone away with a flat battery, or a
pet's tag (which never leaves for long) not heard for a day.

Silence alone raises nothing for the rest (a phone on holiday, a suitcase),
and the repair goes as soon as the thing is heard again or forgotten.
"""
import json
import time
import types
from pathlib import Path

import sextant
from conftest import make_hass

LAYOUT = {"thing_battery_entity": {"primrose": "sensor.primrose_battery"}, "thing_names": {"primrose": "Primrose"},
          "tuning": {"stale_after_secs": 120.0, "away_after_secs": 900.0}}
KEY = ("sextant", "dead_thing_primrose")


def _hass(battery):
    hass = make_hass()
    states = {"sensor.primrose_battery": types.SimpleNamespace(state=battery)}
    hass.states = types.SimpleNamespace(get=states.get)
    return hass


def _heard(hours_ago, ent="primrose"):
    sextant._last_seen.clear()
    sextant._last_seen[ent] = {"zone": "Foyer", "floor": "Ground Floor", "updated": time.time() - hours_ago * 3600}


def test_raised_once_away_with_a_flat_battery_and_cleared_when_heard():
    hass = _hass("1.0")
    _heard(85)
    sextant._update_dead_issues(hass, LAYOUT)
    issue = hass.data["issues"][KEY]
    assert issue["translation_placeholders"] == {"name": "Primrose", "age": "3 days", "where": "Foyer, Ground Floor", "battery": " Its battery last read 1%."}
    sextant._update_dead_issues(hass, LAYOUT)
    assert list(hass.data["issues"]) == [KEY], "the same id every cycle: never a second repair"
    _heard(0)
    sextant._update_dead_issues(hass, LAYOUT)
    assert not hass.data["issues"], "heard again: the repair is gone"


def test_a_pets_tag_is_dead_after_a_day_of_silence_whatever_its_battery():
    layout = {**LAYOUT, "thing_classes": {"primrose": "dog"}}
    for battery, hours, dead in (("80", 25, True), ("unavailable", 25, True), ("80", 23, False)):
        hass = _hass(battery)
        _heard(hours)
        sextant._update_dead_issues(hass, layout)
        assert (KEY in hass.data.get("issues", {})) is dead, (battery, hours)
    hass = _hass("unavailable")
    _heard(25)
    sextant._update_dead_issues(hass, layout)
    assert hass.data["issues"][KEY]["translation_placeholders"]["battery"] == "", "no level to quote"


def test_always_home_is_the_class_unless_the_thing_says_otherwise():
    hass = _hass("80")
    _heard(25)
    sextant._update_dead_issues(hass, {**LAYOUT, "thing_classes": {"primrose": "dog"}, "thing_always_home": {"primrose": False}})
    assert not hass.data.get("issues"), "a dog that boards for days: switched off for her"
    _heard(25, "tile")
    sextant._update_dead_issues(hass, {"thing_classes": {"tile": "tag"}, "thing_always_home": {"tile": True}})
    assert list(hass.data["issues"]) == [("sextant", "dead_thing_tile")], "a tag that never leaves the office: switched on"


def test_not_raised_for_a_thing_that_is_only_away_or_only_low():
    # Not a pet's: away for days with a good battery, or low but still heard.
    for battery, hours in (("80", 85), ("unavailable", 85), ("1.0", 0.1)):
        hass = _hass(battery)
        _heard(hours)
        sextant._update_dead_issues(hass, LAYOUT)
        assert not hass.data.get("issues"), (battery, hours)
    # A phone gone for a week, no battery sensor: away, not dead.
    hass = _hass("1.0")
    _heard(170, "phone")
    sextant._update_dead_issues(hass, {"thing_classes": {"phone": "phone"}})
    assert not hass.data.get("issues")


def test_a_flat_battery_does_not_wait_the_day():
    hass = _hass("4")
    _heard(2)
    sextant._update_dead_issues(hass, LAYOUT)
    assert hass.data["issues"][KEY]["translation_placeholders"]["age"] == "2 hours"


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
