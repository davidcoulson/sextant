"""sextant.get_map (export.py): the plan and who is where, in metres."""
import types

import pytest

from sextant import export


def rect(name, x0, y0, x1, y1, **extra):
    return {"entity_id": name, "poly": True, "cords": [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}], **extra}


def layout():
    return {
        "thing_classes": {"phone": "phone", "cat_tag": "cat"},
        "thing_owners": {"phone": "person.david", "cat_tag": "person.meg"},
        "floor": [
            {
                "name": "Ground", "scale": 100.0, "level": 0, "floor_id": "ground",
                "zones": [
                    rect("Kitchen", 0, 0, 400, 300, zone_id="z1", area_id="kitchen"),
                    rect("Hall", 400, 0, 800, 300, zone_id="z2"),          # shares a wall with the kitchen
                    rect("Garage", 1200, 0, 1600, 300, zone_id="z3"),      # 4 m from the hall: not a neighbour
                    rect("Void", 0, 400, 100, 500, zone_id="z4", no_go=True),
                ],
                "subzones": [rect("Table", 100, 100, 200, 150, parent="z1"), rect("Bench", 1300, 100, 1350, 150)],
                "receivers": [{"entity_id": "kitchen_proxy", "cords": {"x": 10, "y": 150}, "height": 1.2},
                              {"entity_id": "attic_proxy", "cords": {"x": 900, "y": 900}, "solve": False}],
                "access_points": [{"ap_id": "a", "mac": "aa:bb", "name": "Hall AP", "cords": {"x": 600, "y": 10}}],
                "radars": [{"radar_id": "r", "device_id": "dev1", "heading": 90, "cords": {"x": 50, "y": 50}}],
            },
            {"name": "Loft", "zones": [rect("Attic", 0, 0, 100, 100, zone_id="z9")]},   # no scale yet
        ],
    }


def rows():
    return [
        {"ent": "phone", "floor": "Ground", "zone": "Kitchen", "sub_zone": "Table", "cords": [150, 120], "conf": 0.8, "since": 1_700_000_000, "updated": 1_700_000_100},
        {"ent": "cat_tag", "floor": "Ground", "zone": "Hall", "sub_zone": None, "cords": [600, 150], "conf": 0.4},
        {"ent": "gone", "floor": "Ground", "zone": "Hall", "cords": [500, 150]},
    ]


def people():
    return [
        {"person": "person.david", "name": "David", "kind": "person", "location": "Table", "floor": "Ground", "room": "Kitchen", "spot": "Table", "presence": "here", "via": "phone"},
        {"person": "person.meg", "name": "Meg", "kind": "pet", "location": "Hall", "floor": "Ground", "room": "Hall", "spot": None, "presence": "quiet", "via": "cat_tag"},
        {"person": "person.jack", "name": "Jack", "kind": "person", "location": "Kent", "floor": "unknown", "room": "unknown", "presence": "away"},
    ]


def test_rooms_come_out_in_metres_with_neighbours_spots_and_proxies():
    out = export.build_map(layout(), rows(), people(), names={"phone": "David's phone"}, now=1_700_000_200,
                           presence_of=lambda ent: "away" if ent == "gone" else "here")
    assert out["units"] == {"length": "m", "area": "m2"} and out["generated_at"].startswith("2023-11-14")
    ground = out["floors"][0]
    assert ground["scaled"] and ground["floor_id"] == "ground" and ground["level"] == 0
    kitchen, hall, garage = ground["rooms"]
    assert kitchen["outline_m"] == [[0, 0], [4, 0], [4, 3], [0, 3]] and kitchen["area_m2"] == 12.0
    assert kitchen["area_id"] == "kitchen" and hall["area_id"] is None
    assert kitchen["neighbours"] == ["Hall"] and hall["neighbours"] == ["Kitchen"] and garage["neighbours"] == []
    assert [s["name"] for s in kitchen["spots"]] == ["Table"] and kitchen["spots"][0]["area_m2"] == 0.5
    assert [s["name"] for s in garage["spots"]] == ["Bench"]      # no parent: found by its corner
    assert kitchen["proxies"] == ["kitchen_proxy"]
    assert [n["name"] for n in ground["no_go"]] == ["Void"] and "area_m2" not in ground["no_go"][0]
    assert ground["proxies"][0] == {"name": "kitchen_proxy", "x_m": 0.1, "y_m": 1.5, "height_m": 1.2, "room": "Kitchen", "in_use": True}
    assert ground["proxies"][1]["room"] is None and ground["proxies"][1]["in_use"] is False
    assert ground["access_points"][0]["room"] == "Hall" and ground["mmwave"][0]["room"] == "Kitchen"


def test_people_and_things_are_listed_in_their_rooms():
    out = export.build_map(layout(), rows(), people(), names={"phone": "David's phone"}, now=1_700_000_200,
                           presence_of=lambda ent: "away" if ent == "gone" else "here")
    kitchen, hall, _garage = out["floors"][0]["rooms"]
    assert kitchen["occupants"] == [{"name": "David", "kind": "person", "spot": "Table"}]
    assert hall["occupants"] == [{"name": "Meg", "kind": "pet", "spot": None}]
    assert [t["name"] for t in kitchen["things"]] == ["David's phone"]
    assert [t["key"] for t in hall["things"]] == ["cat_tag"]       # "gone" is away: not in the room
    phone = out["things"][0]
    assert phone["x_m"] == 1.5 and phone["y_m"] == 1.2 and phone["owner"] == "person.david" and phone["class"] == "phone"
    assert phone["in_room_since"] == "2023-11-14T22:13:20+00:00" and phone["last_heard"].endswith("22:15:00+00:00")
    assert [p["name"] for p in out["people"]] == ["David", "Meg", "Jack"]


def test_an_unscaled_floor_gives_pixels_and_a_floor_filter_narrows():
    out = export.build_map(layout(), rows(), people(), now=0)
    loft = out["floors"][1]
    assert loft["scaled"] is False and loft["rooms"][0]["outline_px"] == [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert loft["rooms"][0]["area_m2"] is None
    only = export.build_map(layout(), rows(), people(), now=0, floor="Ground")
    assert [f["name"] for f in only["floors"]] == ["Ground"] and [p["name"] for p in only["people"]] == ["David", "Meg"]
    with pytest.raises(ValueError, match="Roof"):
        export.build_map(layout(), floor="Roof")


def test_a_legacy_rectangle_is_ordered_around_its_centre():
    scan = {"entity_id": "R", "cords": [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 0, "y": 100}, {"x": 100, "y": 100}]}
    out = export.build_map({"floor": [{"name": "F", "scale": 100, "zones": [scan]}]}, now=0)
    assert out["floors"][0]["rooms"][0]["area_m2"] == 1.0


def test_people_from_states_reads_the_person_and_pet_sensors():
    states = {
        "sensor.david_sextant_person_location": types.SimpleNamespace(state="Table", attributes={"floor": "Ground", "room": "Kitchen", "spot": "Table", "presence": "here", "via": "phone", "source": "ble"}),
        "sensor.meg_sextant_pet_location": types.SimpleNamespace(state="Hall", attributes={"floor": "Ground", "room": "Hall", "spot": None, "presence": "quiet", "via": "cat_tag"}),
        "person.david": types.SimpleNamespace(state="home", attributes={"friendly_name": "David C"}),
    }
    out = export.people_from_states(states.get, layout())
    assert [(p["name"], p["kind"], p["location"]) for p in out] == [("David C", "person", "Table"), ("meg", "pet", "Hall")]
