"""The Property view's geometry (property_view.py)."""
import math

import sextant  # noqa: F401
from sextant import property_view

S = 100.0


def _room(name, x0, y0, x1, y1):
    return {"entity_id": name, "poly": True, "cords": [{"x": x0 * S, "y": y0 * S}, {"x": x1 * S, "y": y0 * S},
                                                        {"x": x1 * S, "y": y1 * S}, {"x": x0 * S, "y": y1 * S}]}


PINS = [{"name": "P1", "cords": {"x": 0, "y": 0}}, {"name": "P2", "cords": {"x": 1000, "y": 0}}, {"name": "P3", "cords": {"x": 0, "y": 500}}]


def _layout(up_shift=0.0):
    up_pins = [{"name": p["name"], "cords": {"x": p["cords"]["x"] + up_shift * S, "y": p["cords"]["y"]}} for p in PINS]
    return {"floor": [
        {"name": "Up", "scale": S, "level": 1, "pins": up_pins, "zones": [_room("Bed", 0 + up_shift, 0, 5 + up_shift, 5)]},
        {"name": "Ground", "scale": S, "level": 0, "pins": PINS,
         "zones": [_room("Kitchen", 0, 0, 5, 5), {"entity_id": "Void", "no_go": True, "cords": _room("x", 1, 1, 2, 2)["cords"]}],
         "receivers": [{"entity_id": "kitchen_proxy", "address": "aa:bb", "cords": {"x": 250, "y": 250}},
                       {"entity_id": "gazebo", "cords": {"x": 900, "y": 250}}],
         "access_points": [{"mac": "8c:ed:e1:00:de:ed", "name": "Kitchen E7", "cords": {"x": 100, "y": 100}}]},
    ], "site": {"lat": 41.5, "lon": -81.7, "rotation": -10}}


def test_every_floor_lands_in_the_house_frame_bottom_first():
    v = property_view.view(_layout(up_shift=2.0))
    assert [f["name"] for f in v["floors"]] == ["Ground", "Up"]
    ground, up = v["floors"]
    assert ground["rooms"] == [{"name": "Kitchen", "points": [[0, 0], [5, 0], [5, 5], [0, 5]]}]   # no-go areas left out
    # Up's plan is drawn 2 m to the right, its anchors too: in the house frame it sits on top of the ground floor.
    assert up["registered"] and [round(c, 3) for c in up["rooms"][0]["points"][0]] == [0, 0]
    assert v["site"] == {"lat": 41.5, "lon": -81.7, "rotation": 350.0}


def test_proxies_say_when_they_are_outdoors_and_access_points_come_along():
    ground = property_view.view(_layout())["floors"][0]
    assert [(p["slug"], p["outdoor"]) for p in ground["proxies"]] == [("kitchen_proxy", False), ("gazebo", True)]
    assert ground["proxies"][0]["x"] == 2.5 and ground["access_points"] == [{"mac": "8c:ed:e1:00:de:ed", "name": "Kitchen E7", "x": 1.0, "y": 1.0}]


def test_frames_carry_live_positions_into_the_house_frame():
    fr = property_view.frames(_layout(up_shift=2.0))
    assert property_view.to_house(fr["Up"], 450, 150) == [2.5, 1.5]
    assert property_view.to_house(fr["Ground"], 450, 150) == [4.5, 1.5]
    assert math.isclose(fr["Ground"]["cos"], 1.0)


def test_an_unregistered_floor_is_drawn_in_its_own_metres():
    layout = _layout()
    for f in layout["floor"]:
        f.pop("pins")
    fr = property_view.frames(layout)
    assert not fr["Ground"]["registered"] and property_view.to_house(fr["Ground"], 300, 200) == [3.0, 2.0]


def test_sites_are_cleaned():
    assert property_view.clean_site({"lat": 41.5, "lon": -81.7}) == {"lat": 41.5, "lon": -81.7, "rotation": 0.0}
    assert property_view.clean_site({"lat": 41.5, "lon": -81.7, "rotation": 725}) ["rotation"] == 5.0
    for bad in (None, {}, {"lat": 95, "lon": 0}, {"lat": 0, "lon": 200}, {"lat": "x", "lon": 1}, {"lat": True, "lon": 1}):
        assert property_view.clean_site(bad) is None
    assert property_view.view({})["floors"] == [] and property_view.view(None)["site"] is None


def test_site_rotation_missing_is_zero_but_nan_is_rejected():
    assert property_view.clean_site({"lat": 41.0, "lon": -81.0})["rotation"] == 0.0
    assert property_view.clean_site({"lat": 41.0, "lon": -81.0, "rotation": float("nan")}) is None
    assert property_view.clean_site({"lat": 41.0, "lon": -81.0, "rotation": -90})["rotation"] == 270.0
