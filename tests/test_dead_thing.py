"""A repair for a thing that looks dead: gone away with a flat battery, or a
pet's tag (which never leaves for long) not heard for a day.

Silence alone raises nothing for the rest (a phone on holiday, a suitcase),
and the repair goes as soon as the thing is heard again or forgotten.
"""
import json
import time
from datetime import datetime, timezone
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
    assert issue["translation_placeholders"] == {"name": "Primrose", "age": "3 days", "where": "Foyer, Ground Floor", "battery": " Its battery last read 1%.", "home": ""}
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


def test_the_class_setting_stands_between_the_thing_and_the_default():
    hass = _hass("80")
    _heard(25, "tile")
    layout = {"thing_classes": {"tile": "tag"}, "class_always_home": {"tag": True, "dog": False}}
    sextant._update_dead_issues(hass, layout)
    assert list(hass.data["issues"]) == [("sextant", "dead_thing_tile")], "every tag, by the class's setting"
    sextant._update_dead_issues(hass, {**layout, "thing_always_home": {"tile": False}})
    assert not hass.data["issues"], "but not this one"
    _heard(25)
    sextant._update_dead_issues(hass, {**layout, "thing_classes": {"primrose": "dog"}})
    assert not hass.data["issues"], "the default for dogs switched off"


def test_home_by_its_own_tracker_but_unheard():
    """Both cars sat in the garage, home by their own GPS, unheard for six days."""
    layout = {"thing_home_entity": {"model_s": "device_tracker.model_s_location"}, "tuning": LAYOUT["tuning"]}
    key = ("sextant", "dead_thing_model_s")

    def run(state, home_for_s, heard_hours_ago=150):
        hass = make_hass()
        tracker = types.SimpleNamespace(state=state, attributes={"friendly_name": "Model S Location"},
                                        last_changed=datetime.fromtimestamp(time.time() - home_for_s, timezone.utc))
        hass.states = types.SimpleNamespace(get={"device_tracker.model_s_location": tracker}.get)
        _heard(heard_hours_ago, "model_s")
        sextant._update_dead_issues(hass, layout)
        return hass.data.get("issues") or {}

    issues = run("home", 3600)
    assert issues[key]["translation_placeholders"]["home"] == " Model S Location says it is home."
    assert not run("not_home", 3600), "away by its own tracker: only away"
    assert not run("home", 60), "just back: the proxies get their fifteen minutes"
    assert not run("home", 3600, heard_hours_ago=0), "home and heard"


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


def test_reconciled_on_a_cycle_with_nothing_to_solve_and_a_bad_map_stops_nothing(monkeypatch):
    """The house's last tag dying leaves no cycle to solve: the repairs are kept from that path too."""
    import inspect
    assert inspect.getsource(sextant).count("_maintain_dead_issues(hass)") >= 4, "both idle branches and the cycle"
    from sextant import layout_check, persons
    assert layout_check.layout_problem({"floor": [], "class_always_home": True}) is not None
    assert persons.always_home({"class_always_home": True, "thing_always_home": []}, "primrose", "dog"), "falls to the default"
    hass = _hass("1.0")
    _heard(85)
    monkeypatch.setattr(sextant, "get_layout", lambda h: LAYOUT)
    monkeypatch.setattr(sextant, "_dead_issues_from", 0.0)
    sextant._maintain_dead_issues(hass)
    assert not hass.data.get("issues"), "just started: the restored times are not judged yet"
    monkeypatch.setattr(sextant, "_dead_issues_from", 1.0)
    sextant._maintain_dead_issues(hass)
    assert KEY in hass.data["issues"]


def test_an_unreadable_sensor_keeps_the_repair_it_raised():
    """Home Assistant restarting leaves the battery sensor unavailable for a while: no news, not good news."""
    hass = _hass("1.0")
    _heard(5)
    sextant._update_dead_issues(hass, LAYOUT)
    assert KEY in hass.data["issues"]
    hass.states = types.SimpleNamespace(get={"sensor.primrose_battery": types.SimpleNamespace(state="unavailable")}.get)
    sextant._update_dead_issues(hass, LAYOUT)
    assert KEY in hass.data["issues"], "kept"
    fresh = make_hass()
    fresh.states = hass.states
    sextant._update_dead_issues(fresh, LAYOUT)
    assert not fresh.data.get("issues"), "but never raised on no reading"
    _heard(0)
    sextant._update_dead_issues(hass, LAYOUT)
    assert KEY not in hass.data["issues"], "heard again clears it all the same"


def test_the_repair_has_its_text():
    en = json.loads((Path(sextant.__file__).parent / "translations" / "en.json").read_text())
    text = en["issues"]["dead_thing"]
    for key in ("name", "age", "where", "battery", "home"):
        assert "{" + key + "}" in text["description"]


def test_restored_sighting_counts_as_fresh_only_briefly_after_restart(monkeypatch):
    monkeypatch.setattr(sextant, "_restored_at", 1000.0)
    assert sextant._graced(880.0, 1100.0) == 1100.0          # heard 2 min before the restart: read as now
    assert sextant._graced(300.0, 1100.0) == 300.0           # heard long before: left alone
    assert sextant._graced(1050.0, 1100.0) == 1050.0         # heard after the restart: left alone
    assert sextant._graced(880.0, 1000.0 + sextant.RESTORE_GRACE_S + 1) == 880.0   # grace over
    monkeypatch.setattr(sextant, "_restored_at", 0.0)
    assert sextant._graced(880.0, 1100.0) == 880.0           # nothing restored
