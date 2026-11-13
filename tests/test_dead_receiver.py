"""A repair for a placed receiver that has been offline for an hour.

Offline is the liveness poller's own word (rl_offline); the hour rides out a
reboot or a firmware update. Unplaced and ignored receivers never get one.
"""
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
