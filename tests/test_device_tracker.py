"""The person tracker is unknown until Sextant's first cycle gives it a fix.

A made-up not_home at creation read as "left", then "arrived", on every code
reload (Primrose's arrival notice, 2026-11-27)."""
import sys
import types

import pytest


class _TrackerEntity:
    """HA's TrackerEntity.state, as 2026.11 derives it: name, else zones or coordinates, else unknown."""
    _attr_in_zones = None
    _attr_location_name = None
    _attr_latitude = None
    _attr_longitude = None

    @property
    def state(self):
        if self._attr_location_name is not None:
            return self._attr_location_name
        if (self._attr_latitude is not None and self._attr_longitude is not None) or self._attr_in_zones is not None:
            return "home" if self._attr_in_zones == ["zone.home"] else "not_home"
        return None


@pytest.fixture
def tracker_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "homeassistant.components.device_tracker", types.SimpleNamespace(
        SourceType=types.SimpleNamespace(GPS="gps", ROUTER="router", BLUETOOTH_LE="bluetooth_le"),
        TrackerEntity=_TrackerEntity))
    monkeypatch.setattr(sys.modules["homeassistant.helpers.device_registry"], "DeviceInfo", dict, raising=False)
    monkeypatch.delitem(sys.modules, "sextant.device_tracker", raising=False)
    import sextant.device_tracker as dt
    yield dt
    sys.modules.pop("sextant.device_tracker", None)


def test_a_new_tracker_is_unknown_not_away(tracker_module):
    t = tracker_module.SextantPersonTracker("Primrose", "primrose", is_pet=True)
    assert t.state is None   # unknown: person entities ignore it; a trigger needs not_from: unknown to
    assert t._attr_extra_state_attributes["presence"] is None


def test_the_first_fix_then_sets_home_or_away(tracker_module):
    t = tracker_module.SextantPersonTracker("Primrose", "primrose", is_pet=True)
    t.set_fix({"location_name": "home", "source_type": "bluetooth_le", "source": "ble", "presence": "here"})
    assert t.state == "home"
    t.set_fix({"location_name": "not_home", "source_type": "gps", "source": "none", "presence": "away"})
    assert t.state == "not_home"
