"""Per-room occupancy (rooms.py) and its binary_sensor platform."""


import sextant  # noqa: F401
from sextant import binary_sensor as platform
from sextant import rooms

LAYOUT = {"floor": [
    {"name": "Ground Floor", "floor_id": "ground", "zones": [
        {"entity_id": "Kitchen", "area_id": "kitchen", "cords": [{"x": 0, "y": 0}] * 3},
        {"entity_id": "Office", "cords": [{"x": 0, "y": 0}] * 3},
        {"entity_id": "Void", "no_go": True, "cords": [{"x": 0, "y": 0}] * 3},
    ]},
    {"name": "Second Floor", "zones": [
        {"entity_id": "Office", "area_id": "office_up", "cords": [{"x": 0, "y": 0}] * 3},
        {"entity_id": "Master Bedroom", "cords": [{"x": 0, "y": 0}] * 3},
    ]},
]}


def test_room_keys_skip_no_go_zones_and_keep_the_links():
    keys = rooms.room_keys(LAYOUT)
    assert [(k["floor"], k["room"]) for k in keys] == [
        ("Ground Floor", "Kitchen"), ("Ground Floor", "Office"), ("Second Floor", "Office"), ("Second Floor", "Master Bedroom")]
    assert keys[0]["area_id"] == "kitchen" and keys[0]["floor_id"] == "ground"
    assert keys[1]["area_id"] is None


def test_a_room_name_shared_by_two_floors_gets_the_floor_in_its_entity_id():
    ids = rooms.ids_for(rooms.room_keys(LAYOUT))
    assert ids[("Ground Floor", "Kitchen")]["entity_id"] == "binary_sensor.kitchen_sextant_occupancy"
    assert ids[("Ground Floor", "Office")]["entity_id"] == "binary_sensor.ground_floor_office_sextant_occupancy"
    assert ids[("Second Floor", "Office")]["entity_id"] == "binary_sensor.second_floor_office_sextant_occupancy"
    # The unique id always carries the floor, whatever the entity id shows.
    assert ids[("Ground Floor", "Kitchen")]["unique_id"] == "sextant_room_occupancy_ground_floor_kitchen"
    assert ids[("Ground Floor", "Office")]["name"] == "Office (Ground Floor) Sextant Occupancy"
    assert ids[("Second Floor", "Master Bedroom")]["name"] == "Master Bedroom Sextant Occupancy"


ROWS = [
    {"ent": "david_phone", "zone": "Kitchen", "floor": "Ground Floor", "sub_zone": "Peninsula"},
    {"ent": "meg", "zone": "Kitchen", "floor": "Ground Floor", "sub_zone": "unknown"},
    {"ent": "wallet", "zone": "Kitchen", "floor": "Ground Floor", "sub_zone": "Pantry"},
    {"ent": "fry", "zone": "Office", "floor": "Ground Floor"},
    {"ent": "leela", "zone": "Office", "floor": "Second Floor"},
    {"ent": "lost_tag", "zone": "unknown", "floor": "Ground Floor"},
    {"ent": "gone", "zone": "Kitchen", "floor": "Ground Floor"},
    {"ent": "luggage", "zone": "Master Bedroom", "floor": "Second Floor"},
    {"ent": "vacuum_r2d2", "zone": "Master Bedroom", "floor": "Second Floor", "robot": "vacuum.r2d2"},
]
PRESENCE = {"david_phone": "here", "meg": "quiet", "fry": "here", "leela": "here", "gone": "away", "wallet": "here", "luggage": "here", "vacuum_r2d2": "here"}
CLASSES = {"meg": "cat", "fry": "cat", "leela": "cat", "david_phone": "phone", "wallet": "wallet", "luggage": "bag"}
NAMES = {"david_phone": "David Phone", "meg": "Meg", "fry": "Fry", "leela": "Leela", "wallet": "Wallet", "luggage": "Luggage"}


def test_occupancy_counts_the_things_placed_in_each_room():
    keys = rooms.room_keys(LAYOUT)
    out = rooms.occupancy(keys, ROWS, PRESENCE.get, CLASSES, NAMES, {"David": ("Ground Floor", "Kitchen")})
    on, kitchen = out[("Ground Floor", "Kitchen")]
    assert on and kitchen["count"] == 2                      # the phone and the cat; not the wallet
    assert kitchen["things"] == ["David Phone", "Wallet", "Meg"]   # here before quiet, everything listed
    assert kitchen["pets"] == ["Meg"] and kitchen["people"] == ["David"]
    assert kitchen["spots"] == ["Peninsula"] and kitchen["presence"] == "here"   # the wallet's Pantry is not a spot in use
    assert kitchen["area_id"] == "kitchen" and kitchen["floor_id"] == "ground"
    # Two rooms called Office, told apart by floor.
    assert out[("Ground Floor", "Office")][1]["things"] == ["Fry"]
    assert out[("Second Floor", "Office")][1]["things"] == ["Leela"]
    # Luggage and a robot vacuum do not make a bedroom occupied; the luggage is still listed.
    on, bedroom = out[("Second Floor", "Master Bedroom")]
    assert not on and bedroom["count"] == 0 and bedroom["presence"] is None
    assert bedroom["things"] == ["Luggage"]


def test_a_person_placed_in_a_room_makes_it_occupied_even_without_a_counted_thing():
    out = rooms.occupancy(rooms.room_keys(LAYOUT), [], PRESENCE.get, CLASSES, NAMES, {"Guest": ("Second Floor", "Master Bedroom")})
    on, bedroom = out[("Second Floor", "Master Bedroom")]
    assert on and bedroom["people"] == ["Guest"] and bedroom["count"] == 0


def test_a_thing_gone_away_or_not_placed_counts_nowhere():
    out = rooms.occupancy(rooms.room_keys(LAYOUT), ROWS, PRESENCE.get, CLASSES, NAMES)
    things = [t for _on, a in out.values() for t in a["things"]]
    assert "gone" not in things and "lost_tag" not in things


def test_a_room_of_only_quiet_things_is_on_but_says_quiet():
    out = rooms.occupancy(rooms.room_keys(LAYOUT), [ROWS[1]], PRESENCE.get, CLASSES, NAMES)
    on, kitchen = out[("Ground Floor", "Kitchen")]
    assert on and kitchen["presence"] == "quiet"


def test_people_home_counts_the_people_heard_and_keeps_the_pets_apart():
    count, attrs = rooms.people_home({"David": "here", "Eilee": "quiet", "Jack": "away", "Michelle": "here", "Meg": "here", "Willow": "away"}, pets={"Meg", "Willow"})
    assert count == 3 and attrs == {"home": ["David", "Eilee", "Michelle"], "away": ["Jack"], "pets_home": ["Meg"]}


# --- the platform --------------------------------------------------------------

def _added(hass):
    hass.data["sextant_room_sensors"] = {}
    hass.data["sextant_room_add"] = lambda entities, update_before_add=False: added.extend(entities)
    added = []
    return added


def test_sensors_are_created_once_per_room_and_pruned_with_the_plan(hass):
    added = _added(hass)
    platform.ensure_room_sensors(hass, LAYOUT)
    assert [s.entity_id for s in added] == [
        "binary_sensor.kitchen_sextant_occupancy", "binary_sensor.ground_floor_office_sextant_occupancy",
        "binary_sensor.second_floor_office_sextant_occupancy", "binary_sensor.master_bedroom_sextant_occupancy"]
    platform.ensure_room_sensors(hass, LAYOUT)
    assert len(added) == 4                                   # nothing created twice
    # The Kitchen is renamed: its sensor (and empty device) go, the new room's comes.
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    dev = dev_reg.add({("sextant", "room_ground_floor_kitchen")})
    ent_reg.add("binary_sensor.kitchen_sextant_occupancy", unique_id="sextant_room_occupancy_ground_floor_kitchen", device_id=dev.id)
    renamed = {"floor": [{"name": "Ground Floor", "zones": [{"entity_id": "Cook House", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    platform.prune_room_sensors(hass, renamed)
    assert ("Ground Floor", "Kitchen") not in hass.data["sextant_room_sensors"]
    assert ent_reg.async_get("binary_sensor.kitchen_sextant_occupancy") is None
    assert dev.id not in dev_reg.devices


def test_the_room_device_is_put_in_its_area_once_and_never_moved_back(hass):
    _added(hass)
    platform.ensure_room_sensors(hass, LAYOUT)
    assert ("Ground Floor", "Kitchen") in hass.data["sextant_room_unlinked"]
    # Not added to HA yet: waits.
    platform.link_room_areas(hass, LAYOUT)
    assert ("Ground Floor", "Kitchen") in hass.data["sextant_room_unlinked"]
    from homeassistant.helpers import device_registry as dr
    dev_reg = dr.async_get(hass)
    dev = dev_reg.add({("sextant", "room_ground_floor_kitchen")})
    for s in hass.data["sextant_room_sensors"].values():
        s.hass = hass
    platform.link_room_areas(hass, LAYOUT)
    assert dev.area_id == "kitchen"
    # Rooms without an area are done; a linked room whose device is not
    # registered yet keeps waiting for the next cycle.
    assert hass.data["sextant_room_unlinked"] == {("Second Floor", "Office")}
    dev.area_id = "pantry"                                   # the user moved it
    hass.data["sextant_room_unlinked"].add(("Ground Floor", "Kitchen"))
    platform.link_room_areas(hass, LAYOUT)
    assert dev.area_id == "pantry"


def test_set_occupancy_writes_only_on_change(hass):
    _added(hass)
    platform.ensure_room_sensors(hass, LAYOUT)
    sensor = hass.data["sextant_room_sensors"][("Ground Floor", "Kitchen")]
    writes = []
    sensor.hass = hass
    sensor.async_write_ha_state = lambda: writes.append(1)
    attrs = {"room": "Kitchen", "count": 1}
    sensor.set_occupancy(True, attrs)
    sensor.set_occupancy(True, dict(attrs))
    assert len(writes) == 1 and sensor._attr_is_on is True
    sensor.set_occupancy(False, {"room": "Kitchen", "count": 0})
    assert len(writes) == 2 and sensor._attr_is_on is False
