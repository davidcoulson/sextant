"""A repair for a placed receiver that has been offline for an hour.

Offline is the liveness poller's own word (rl_offline); the hour rides out a
reboot or a firmware update. Unplaced and ignored receivers never get one.
"""
import asyncio
import types

import sextant
from conftest import make_hass

LAYOUT = {"floor": [{"name": "Ground Floor", "receivers": [
    {"entity_id": "garage_proxy", "address": "AA:BB:CC:00:00:01"},
    {"entity_id": "kiosk", "address": "AA:BB:CC:00:00:02"},
]}], "ignored_scanners": ["aa:bb:cc:00:00:02"]}
KEY = ("sextant", "dead_receiver_garage_proxy")
T0 = 1_000_000.0


def _hass(offline):
    hass = make_hass()
    hass.data[sextant.DOMAIN] = {"rl_offline": list(offline)}
    return hass


def test_raised_after_an_hour_offline_and_cleared_when_back():
    hass = _hass(["garage_proxy"])
    sextant._update_receiver_issues(hass, LAYOUT, T0)
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 3500)
    assert not hass.data.get("issues"), "a reboot or an update: not yet"
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 7300)
    assert hass.data["issues"][KEY]["translation_placeholders"] == {"name": "garage_proxy", "where": "Ground Floor", "age": "2 hours"}
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 7400)
    assert list(hass.data["issues"]) == [KEY], "the same id every poll"
    hass.data[sextant.DOMAIN]["rl_offline"] = []
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 7500)
    assert not hass.data["issues"], "heard again"
    hass.data[sextant.DOMAIN]["rl_offline"] = ["garage_proxy"]
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 7600)
    assert not hass.data["issues"], "and the hour starts over"


def test_not_raised_for_an_ignored_or_unplaced_receiver():
    hass = _hass(["kiosk", "somewhere_else"])
    sextant._update_receiver_issues(hass, LAYOUT, T0)
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 7300)
    assert not hass.data.get("issues")


def test_cleared_when_taken_off_the_plan():
    hass = _hass(["garage_proxy"])
    sextant._update_receiver_issues(hass, LAYOUT, T0)
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 3700)
    assert KEY in hass.data["issues"]
    sextant._update_receiver_issues(hass, {"floor": [{"name": "Ground Floor", "receivers": []}]}, T0 + 3800)
    assert not hass.data["issues"]


def test_cleared_when_the_receiver_is_ignored_and_one_repair_for_a_slug_on_two_floors():
    hass = _hass(["garage_proxy"])
    two = {"floor": LAYOUT["floor"] + [{"name": "Basement", "receivers": [{"entity_id": "garage_proxy", "address": "AA:BB:CC:00:00:01"}]}]}
    sextant._update_receiver_issues(hass, two, T0)
    sextant._update_receiver_issues(hass, two, T0 + 3600)
    assert list(hass.data["issues"]) == [KEY], "raised on the hour, once"
    sextant._update_receiver_issues(hass, {**two, "ignored_scanners": ["aa:bb:cc:00:00:01"]}, T0 + 3700)
    assert not hass.data["issues"]


def test_an_offline_that_is_only_a_guess_raises_nothing():
    hass = _hass(["garage_proxy"])
    hass.data[sextant.DOMAIN]["rl_offline_guessed"] = ["garage_proxy"]
    sextant._update_receiver_issues(hass, LAYOUT, T0)
    sextant._update_receiver_issues(hass, LAYOUT, T0 + 7300)
    assert not hass.data.get("issues")


def test_the_poller_tells_a_guess_from_a_proxy_bermuda_has_dropped(monkeypatch):
    """Neither proxy has an age, a status sensor, a device or a reading. The
    garage one Bermuda no longer lists at all (it is down); the attic one has
    no address to look up, so nothing says more than that no tag is near it."""
    layout = {"floor": [{"name": "Ground Floor", "receivers": [{"entity_id": "garage_proxy", "address": "AA:BB:CC:00:00:01"}]}]}
    hass = make_hass()
    hass.states = types.SimpleNamespace(get=lambda eid: None)
    src = sextant.bermuda_source

    async def _no_resolve(h):
        return None

    monkeypatch.setattr(sextant, "async_resolve_receiver_addresses", _no_resolve)
    monkeypatch.setattr(sextant, "get_layout", lambda h: layout)
    monkeypatch.setattr(sextant, "_scanner_slugs_and_readings", lambda h: ({"garage_proxy", "attic_proxy"}, set()))
    monkeypatch.setattr(sextant, "_build_device_availability", lambda h: ({}, {}))
    monkeypatch.setattr(src, "async_get_scanner_ages", lambda h: {"hall_proxy": 2.0})
    monkeypatch.setattr(src, "async_get_scanner_directory", lambda h: {"aa:bb:cc:00:00:09": {"slug": "hall_proxy", "last_seen_age": 2.0}})
    asyncio.run(sextant.update_receiver_liveness(hass))
    dom = hass.data[sextant.DOMAIN]
    assert dom["rl_offline"] == ["attic_proxy", "garage_proxy"]
    assert dom["rl_offline_guessed"] == ["attic_proxy"]
    # Before Bermuda has loaded there is no list to be missing from: both are guesses.
    monkeypatch.setattr(src, "async_get_scanner_directory", lambda h: None)
    asyncio.run(sextant.update_receiver_liveness(hass))
    assert dom["rl_offline_guessed"] == ["attic_proxy", "garage_proxy"]
