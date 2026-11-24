import json
"""Per-room occupancy (rooms.py) and its binary_sensor platform."""


import types
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
    {"ent": "alex_phone", "zone": "Kitchen", "floor": "Ground Floor", "sub_zone": "Peninsula"},
    {"ent": "meg", "zone": "Kitchen", "floor": "Ground Floor", "sub_zone": "unknown"},
    {"ent": "wallet", "zone": "Kitchen", "floor": "Ground Floor", "sub_zone": "Pantry"},
    {"ent": "fry", "zone": "Office", "floor": "Ground Floor"},
    {"ent": "leela", "zone": "Office", "floor": "Second Floor"},
    {"ent": "lost_tag", "zone": "unknown", "floor": "Ground Floor"},
    {"ent": "gone", "zone": "Kitchen", "floor": "Ground Floor"},
    {"ent": "luggage", "zone": "Master Bedroom", "floor": "Second Floor"},
    {"ent": "vacuum_r2d2", "zone": "Master Bedroom", "floor": "Second Floor", "robot": "vacuum.r2d2"},
]
PRESENCE = {"alex_phone": "here", "meg": "quiet", "fry": "here", "leela": "here", "gone": "away", "wallet": "here", "luggage": "here", "vacuum_r2d2": "here"}
CLASSES = {"meg": "cat", "fry": "cat", "leela": "cat", "alex_phone": "phone", "wallet": "wallet", "luggage": "bag"}
NAMES = {"alex_phone": "Alex Phone", "meg": "Meg", "fry": "Fry", "leela": "Leela", "wallet": "Wallet", "luggage": "Luggage"}


def test_occupancy_counts_the_things_placed_in_each_room():
    keys = rooms.room_keys(LAYOUT)
    out = rooms.occupancy(keys, ROWS, PRESENCE.get, CLASSES, NAMES, {"Alex": ("Ground Floor", "Kitchen")})
    on, kitchen = out[("Ground Floor", "Kitchen")]
    assert on and kitchen["count"] == 2                      # the phone and the cat; not the wallet
    assert kitchen["things"] == ["Alex Phone", "Wallet", "Meg"]   # here before quiet, everything listed
    assert kitchen["pets"] == ["Meg"] and kitchen["people"] == ["Alex"]
    assert kitchen["ids"] == {"Alex Phone": "alex_phone", "Wallet": "wallet", "Meg": "meg"}
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


def test_a_thing_outside_is_not_in_its_nearest_room():
    out_row = {"ent": "meg", "zone": "Kitchen", "floor": "Ground Floor", "outside": True}
    on, kitchen = rooms.occupancy(rooms.room_keys(LAYOUT), [out_row], PRESENCE.get, CLASSES, NAMES)[("Ground Floor", "Kitchen")]
    assert not on and kitchen["pets"] == [] and kitchen["things"] == []


def test_a_room_of_only_quiet_things_is_on_but_says_quiet():
    out = rooms.occupancy(rooms.room_keys(LAYOUT), [ROWS[1]], PRESENCE.get, CLASSES, NAMES)
    on, kitchen = out[("Ground Floor", "Kitchen")]
    assert on and kitchen["presence"] == "quiet"


def test_an_owned_thing_counts_only_while_it_speaks_for_its_owner():
    owners = {"alex_phone": "person.alex", "alex_watch": "person.alex", "meg": "person.meg"}
    by_class = lambda ent: ent in ("alex_phone", "alex_watch", "meg", "guest_phone", "wallet") and ent != "wallet"
    counts = rooms.stands_for_someone(owners, {"alex_phone", "meg"}, by_class)
    assert counts("alex_phone") and counts("meg")
    assert not counts("alex_watch")          # on the bedside table; Alex is spoken for by his phone
    assert counts("guest_phone")               # nobody's: its class decides
    assert not counts("wallet")
    # The watch speaks for Alex once he wears it and leaves the phone behind.
    assert rooms.stands_for_someone(owners, {"alex_watch"}, by_class)("alex_watch")


def test_people_home_counts_the_people_heard_and_keeps_the_pets_apart():
    count, attrs = rooms.people_home({"Alex": "here", "Robin": "quiet", "Jamie": "away", "Sam": "here", "Meg": "here", "Willow": "away"}, pets={"Meg", "Willow"})
    assert count == 3 and attrs == {"home": ["Alex", "Robin", "Sam"], "away": ["Jamie"], "pets_home": ["Meg"]}


# --- the platform --------------------------------------------------------------

def _added(hass):
    hass.data["sextant_room_sensors"] = {}
    hass.data["sextant_room_add"] = lambda entities, update_before_add=False: added.extend(entities)
    added = []
    return added


def test_sensors_are_created_once_per_room_and_pruned_with_the_plan(hass):
    added = _added(hass)
    platform.ensure_room_sensors(hass, LAYOUT)
    assert [s.entity_id for s in added if "people" not in s.entity_id] == [
        "binary_sensor.kitchen_sextant_occupancy", "binary_sensor.ground_floor_office_sextant_occupancy",
        "binary_sensor.second_floor_office_sextant_occupancy", "binary_sensor.master_bedroom_sextant_occupancy"]
    assert len(added) == 8                                   # each room has a people-only sensor too
    platform.ensure_room_sensors(hass, LAYOUT)
    assert len(added) == 8                                   # nothing created twice
    # The Kitchen is renamed: its sensor (and empty device) go, the new room's comes.
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    dev = dev_reg.add({("sextant", "room_ground_floor_kitchen")})
    ent_reg.add("binary_sensor.kitchen_sextant_occupancy", unique_id="sextant_room_occupancy_ground_floor_kitchen", device_id=dev.id)
    ent_reg.add("binary_sensor.kitchen_sextant_people_occupancy", unique_id="sextant_room_people_ground_floor_kitchen", device_id=dev.id)
    renamed = {"floor": [{"name": "Ground Floor", "zones": [{"entity_id": "Cook House", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    platform.prune_room_sensors(hass, renamed)
    assert ("Ground Floor", "Kitchen") not in hass.data["sextant_room_sensors"]
    assert ent_reg.async_get("binary_sensor.kitchen_sextant_occupancy") is None
    assert ent_reg.async_get("binary_sensor.kitchen_sextant_people_occupancy") is None
    assert ("Ground Floor", "Kitchen") not in hass.data["sextant_room_people"]
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


def test_two_names_that_slug_the_same_stay_two_sensors():
    layout = {"floor": [{"name": "Ground Floor", "zones": [
        {"entity_id": "Guest Room", "cords": [{"x": 0, "y": 0}] * 3},
        {"entity_id": "Guest-Room", "cords": [{"x": 0, "y": 0}] * 3},
    ]}]}
    ids = rooms.ids_for(rooms.room_keys(layout))
    a, b = ids[("Ground Floor", "Guest Room")], ids[("Ground Floor", "Guest-Room")]
    assert a["entity_id"].startswith("binary_sensor.guest_room_") and b["entity_id"].startswith("binary_sensor.guest_room_")
    assert a["entity_id"] != b["entity_id"] and a["unique_id"] != b["unique_id"]
    # Neither is the plain slug, so neither depends on which was drawn first...
    assert a["entity_id"] != "binary_sensor.guest_room_sextant_occupancy"
    layout["floor"][0]["zones"].reverse()
    assert rooms.ids_for(rooms.room_keys(layout))[("Ground Floor", "Guest Room")] == a
    # ...and alone, a room has its plain slug.
    del layout["floor"][0]["zones"][0]
    assert rooms.ids_for(rooms.room_keys(layout))[("Ground Floor", "Guest Room")]["entity_id"] == "binary_sensor.guest_room_sextant_occupancy"


def test_a_twin_left_alone_takes_the_plain_ids_registry_entry_included(hass):
    _added(hass)
    twins = {"floor": [{"name": "Ground Floor", "zones": [
        {"entity_id": "Guest Room", "cords": [{"x": 0, "y": 0}] * 3}, {"entity_id": "Guest-Room", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    platform.ensure_room_sensors(hass, twins)
    sensor = hass.data["sextant_room_sensors"][("Ground Floor", "Guest Room")]
    old_entity_id, old_unique_id = sensor.entity_id, sensor._attr_unique_id
    from homeassistant.helpers import entity_registry as er
    ent_reg = er.async_get(hass)
    ent_reg.add(old_entity_id, unique_id=old_unique_id)
    alone = {"floor": [{"name": "Ground Floor", "zones": [{"entity_id": "Guest Room", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    platform.prune_room_sensors(hass, alone)
    platform.ensure_room_sensors(hass, alone)
    assert sensor.entity_id == "binary_sensor.guest_room_sextant_occupancy"
    assert sensor._attr_unique_id == "sextant_room_occupancy_ground_floor_guest_room"
    entry = ent_reg.async_get("binary_sensor.guest_room_sextant_occupancy")
    assert entry is not None and entry.unique_id == sensor._attr_unique_id
    assert ent_reg.async_get(old_entity_id) is None


def test_a_room_that_gains_a_namesake_moves_to_the_floor_qualified_id(hass):
    _added(hass)
    one = {"floor": [{"name": "Ground Floor", "zones": [{"entity_id": "Office", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    platform.ensure_room_sensors(hass, one)
    sensor = hass.data["sextant_room_sensors"][("Ground Floor", "Office")]
    assert sensor.entity_id == "binary_sensor.office_sextant_occupancy"
    from homeassistant.helpers import entity_registry as er
    ent_reg = er.async_get(hass)
    ent_reg.add("binary_sensor.office_sextant_occupancy", unique_id=sensor._attr_unique_id)
    two = {"floor": one["floor"] + [{"name": "Second Floor", "zones": [{"entity_id": "Office", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    platform.ensure_room_sensors(hass, two)
    assert sensor.entity_id == "binary_sensor.ground_floor_office_sextant_occupancy"
    assert sensor._attr_name == "Office (Ground Floor) Sextant Occupancy"
    assert ent_reg.async_get("binary_sensor.ground_floor_office_sextant_occupancy") is not None
    assert ent_reg.async_get("binary_sensor.office_sextant_occupancy") is None
    assert hass.data["sextant_room_sensors"][("Second Floor", "Office")].entity_id == "binary_sensor.second_floor_office_sextant_occupancy"


def test_people_home_with_nobody_is_zero():
    assert rooms.people_home({}) == (0, {"home": [], "away": [], "pets_home": []})


def test_settle_holds_extends_and_clears():
    s = rooms.settle(None, True, 100.0, hold_s=60.0, extended_s=300.0)
    assert (s["on"], s["state"], s["since"]) == (True, "occupied", 100.0)
    s = rooms.settle(s, True, 450.0, 60.0, 300.0)
    assert (s["state"], s["since"]) == ("extended", 100.0)
    s = rooms.settle(s, False, 470.0, 60.0, 300.0)             # inside the hold: still on, same stay
    assert (s["on"], s["state"], s["since"]) == (True, "extended", 100.0)
    s = rooms.settle(s, False, 520.0, 60.0, 300.0)             # hold over (last reading at 450)
    assert (s["on"], s["state"], s["since"]) == (False, "clear", 520.0)
    assert rooms.settle(None, False, 5.0)["state"] == "clear"   # no hold, never seen: clear


def test_floor_and_house_occupancy_sum_the_rooms():
    keys = rooms.room_keys(LAYOUT)
    answers = {("Ground Floor", "Kitchen"): (True, {"people": ["Ann"], "pets": [], "count": 1}),
               ("Second Floor", "Master Bedroom"): (False, {"people": [], "pets": ["Meg"], "count": 0})}
    floors, house = rooms.aggregate(keys, answers)
    assert floors["Ground Floor"][0] is True and floors["Ground Floor"][1]["rooms"] == ["Kitchen"]
    assert floors["Second Floor"][0] is False
    assert house[0] is True and house[1]["people"] == ["Ann"] and house[1]["rooms"] == ["Ground Floor: Kitchen"]
    assert rooms.aggregate(keys, {})[1][0] is False
    assert rooms.floor_ids(keys)["Second Floor"]["entity_id"] == "binary_sensor.second_floor_sextant_floor_occupancy"


def test_the_force_switch_sits_beside_its_room_sensor():
    ids = rooms.ids_for(rooms.room_keys(LAYOUT))[("Ground Floor", "Kitchen")]
    sw = rooms.switch_ids(ids)
    assert sw["entity_id"] == "switch.kitchen_sextant_force_occupied" and sw["unique_id"] == "sextant_room_force_ground_floor_kitchen"
    assert sw["name"] == "Kitchen Force Occupied"


def test_publish_rooms_holds_forces_and_sums(hass):
    from sextant import switch as sw_platform
    added = _added(hass)
    hass.data["sextant_room_keys"] = rooms.room_keys(LAYOUT)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, LAYOUT)
    platform.ensure_aggregate_sensors(hass, LAYOUT)
    hass.data["sextant_room_switches"], hass.data["sextant_switch_add"] = {}, lambda e, **k: None
    sw_platform.ensure_room_switches(hass, LAYOUT)
    kitchen = ("Ground Floor", "Kitchen")
    hass.data["sextant_room_answers"] = {kitchen: (False, None)}
    sextant._publish_rooms(hass)
    assert hass.data["sextant_room_sensors"][kitchen]._attr_is_on is False
    hass.data["sextant_room_switches"][kitchen]._attr_is_on = True        # "force occupied"
    sextant._publish_rooms(hass)
    sensor = hass.data["sextant_room_sensors"][kitchen]
    assert sensor._attr_is_on is True and sensor._attr_extra_state_attributes["forced"] is True
    house = hass.data["sextant_aggregate_sensors"][("house", None)]
    assert house._attr_is_on is True
    # forced counts as people; a pet alone does not turn the people roll-ups on
    assert hass.data["sextant_aggregate_sensors"][("house_people", None)]._attr_is_on is True
    hass.data["sextant_room_switches"][kitchen]._attr_is_on = False
    hass.data["sextant_room_answers"] = {kitchen: (True, {"room": "Kitchen", "floor": "Ground Floor", "count": 1, "humans": 0, "people": [],
                                                           "pets": ["Fry"], "things": []})}
    hass.data["sextant_room_sensors"][kitchen].memory = hass.data["sextant_room_people"][kitchen].memory = None
    sextant._publish_rooms(hass)
    assert house._attr_is_on is True
    people = hass.data["sextant_aggregate_sensors"][("house_people", None)]
    assert people._attr_is_on is False and people.entity_id == "binary_sensor.sextant_house_people_occupancy"
    assert hass.data["sextant_aggregate_sensors"][("floor_people", "Ground Floor")].entity_id == "binary_sensor.ground_floor_sextant_floor_people_occupancy"
    assert people._attr_device_info["identifiers"] == house._attr_device_info["identifiers"]


def test_floor_ids_separate_floors_that_slug_the_same():
    keys = rooms.room_keys({"floor": [{"name": "Guest Floor", "zones": [{"entity_id": "A", "cords": [{"x": 0, "y": 0}] * 3}]},
                                      {"name": "Guest-Floor", "zones": [{"entity_id": "B", "cords": [{"x": 0, "y": 0}] * 3}]}]})
    ids = rooms.floor_ids(keys)
    assert len({v["unique_id"] for v in ids.values()}) == 2 and len({v["entity_id"] for v in ids.values()}) == 2


def test_room_options_are_read_safely():
    z = {"entity_id": "X", "room_hold_secs": 45, "room_extended_secs": 5, "inputs": "binary_sensor.m, media_player.tv, junk",
         "door": "binary_sensor.d"}
    o = rooms.room_options(z)
    none = {"keep": [], "mode_entity": None, "mode_label": None, "dark": None, "sleep_entity": None, "sleep_hold_secs": None, "extended_hold_secs": None}
    assert o == {"hold_secs": 45.0, "extended_secs": None, "inputs": ["binary_sensor.m", "media_player.tv"], "door": "binary_sensor.d", **none}
    assert rooms.room_options({"room_hold_secs": True, "inputs": 7, "door": ["x"]}) == {"hold_secs": None, "extended_secs": None, "inputs": [], "door": None, **none}
    o = rooms.room_options({"inputs": "binary_sensor.m", "keep": "media_player.tv, binary_sensor.m, sensor.w>20", "mode_entity": "input_select.scene",
                            "mode_label": " Movie ", "dark": "sensor.lux<20", "sleep_entity": "input_boolean.asleep", "room_sleep_hold_secs": 1800})
    assert o["keep"] == ["media_player.tv", "sensor.w>20"] and o["mode_entity"] == "input_select.scene" and o["mode_label"] == "Movie"
    assert o["dark"] == "sensor.lux<20" and o["sleep_entity"] == "input_boolean.asleep" and o["sleep_hold_secs"] == 1800.0


def test_mode_dark_and_the_hold_that_applies():
    assert rooms.mode_of("Movie") == "Movie" and rooms.mode_of("on", "Guests") == "Guests" and rooms.mode_of("playing") == "on"
    assert rooms.mode_of("Idle", option=True) == "Idle" and rooms.mode_of("Home", "x", True) == "Home" and rooms.mode_of("unknown", option=True) is None
    assert rooms.mode_of("off") is None and rooms.mode_of("unavailable") is None and rooms.mode_of(None) is None
    states = {"sensor.lux": "12", "sun.sun": "above_horizon"}
    assert rooms.is_dark("sensor.lux<20", states.get) is True and rooms.is_dark(None, states.get) is False
    assert rooms.is_dark("sensor.gone<20", states.get) is None and rooms.is_dark(None, {}.get) is None
    assert rooms.hold_for(False, False, 60, 1800, 300) == 60 and rooms.hold_for(True, True, 60, 1800, 300) == 1800
    assert rooms.hold_for(False, True, 60, 1800, 300) == 300 and rooms.hold_for(True, True, 60, -1, None) == 60


def test_publish_rooms_keep_sleep_mode_event_and_force_auto_off(hass, monkeypatch):
    layout = {"tuning": {"room_force_max_secs": 60}, "floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [
        {"entity_id": "Den", "inputs": "binary_sensor.den_motion", "keep": "media_player.den_tv", "mode_entity": "input_select.den",
         "sleep_entity": "input_boolean.den_asleep", "room_sleep_hold_secs": 900, "cords": [{"x": 0, "y": 0}] * 3}]}]}
    from sextant import switch as sw_platform
    _added(hass)
    monkeypatch.setattr(sextant, "get_layout", lambda h: layout)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"], hass.data["sextant_switch_add"] = {}, lambda e, **k: None
    sw_platform.ensure_room_switches(hass, layout)
    key = ("Ground Floor", "Den")
    states = {"binary_sensor.den_motion": "off", "media_player.den_tv": "playing", "input_select.den": "Movie", "input_boolean.den_asleep": "off"}
    hass.states = type("S", (), {"get": staticmethod(lambda e: type("St", (), {"state": states[e]})() if e in states else None)})()
    fired = hass.events
    hass.data["sextant_room_answers"] = {key: (False, None)}
    clock = [1000.0]
    monkeypatch.setattr(sextant.time, "time", lambda: clock[0])
    monkeypatch.setattr(sextant, "_rooms_from", 1.0)      # long past the settle after a start, when no room event fires
    sensor = hass.data["sextant_room_sensors"][key]
    sextant._publish_rooms(hass)
    assert sensor._attr_is_on is False and not fired                 # the TV alone never starts a stay
    states["binary_sensor.den_motion"] = "on"
    sextant._publish_rooms(hass)
    attrs = sensor._attr_extra_state_attributes
    assert sensor._attr_is_on is True and attrs["mode"] == "Movie" and attrs["asleep"] is False
    assert fired[-1][0] == "sextant_room_occupancy_changed" and fired[-1][1]["state"] == "occupied" and fired[-1][1]["previous"] == "clear"
    states["binary_sensor.den_motion"] = "off"
    sextant._publish_rooms(hass)
    attrs = sensor._attr_extra_state_attributes
    assert sensor._attr_is_on is True and "keep" in attrs["sources"] and attrs["hold_over"] is False   # the TV keeps it
    states["media_player.den_tv"], states["input_boolean.den_asleep"] = "off", "on"
    clock[0] += 600
    sextant._publish_rooms(hass)
    assert sensor._attr_is_on is True and sensor._attr_extra_state_attributes["hold_over"] is True      # asleep: 900 s, not 0
    states["input_boolean.den_asleep"] = "off"
    sextant._publish_rooms(hass)
    assert sensor._attr_is_on is False and [d["state"] for _n, d in fired] == ["occupied", "extended", "clear"]
    switch = hass.data["sextant_room_switches"][key]
    switch._attr_is_on, switch.on_since, switch.async_write_ha_state = True, clock[0], lambda: None
    sextant._publish_rooms(hass)
    assert sensor._attr_is_on is True
    clock[0] += 61
    sextant._publish_rooms(hass)
    assert switch._attr_is_on is False and sensor._attr_is_on is False                                   # the force switch timed out


def test_the_sleep_hold_ends_when_its_people_are_seen_in_another_room(hass, monkeypatch):
    # The asleep helper here is "night and the room is on", so a sleep hold that kept the
    # room on after everyone got up would keep the helper on, and so itself, for hours.
    layout = {"floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [
        {"entity_id": "Bedroom", "sleep_entity": "binary_sensor.bedroom_asleep", "room_sleep_hold_secs": 7200, "cords": [{"x": 0, "y": 0}] * 3}]}]}
    _added(hass)
    monkeypatch.setattr(sextant, "get_layout", lambda h: layout)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"] = {}
    key, kitchen = ("Ground Floor", "Bedroom"), ("Ground Floor", "Kitchen")
    hass.states = type("S", (), {"get": staticmethod(lambda e: type("St", (), {"state": "on"})())})()   # asleep throughout
    clock = [1000.0]
    monkeypatch.setattr(sextant.time, "time", lambda: clock[0])
    anyone, who = hass.data["sextant_room_sensors"][key], hass.data["sextant_room_people"][key]
    here = {"room": "Bedroom", "floor": "Ground Floor", "count": 2, "humans": 2, "people": ["David", "Michelle"], "pets": []}
    hass.data["sextant_room_answers"] = {key: (True, here)}
    sextant._publish_rooms(hass)
    assert anyone._attr_is_on is True and who._attr_is_on is True
    gone = (False, {**here, "count": 0, "humans": 0, "people": []})
    hass.data["sextant_room_answers"] = {key: gone}                          # seen nowhere (flat phones): the sleep hold keeps the room
    clock[0] += 600
    sextant._publish_rooms(hass)
    assert anyone._attr_is_on is True and who._attr_is_on is True and anyone._attr_extra_state_attributes["hold_over"] is True
    hass.data["sextant_room_answers"] = {key: gone, kitchen: (True, {"people": ["David"]})}
    sextant._publish_rooms(hass)
    assert anyone._attr_is_on is True and who._attr_is_on is True              # one of the two is up: the other may still be asleep
    hass.data["sextant_room_answers"] = {key: gone, kitchen: (True, {"people": ["David", "Michelle"]})}
    sextant._publish_rooms(hass)
    assert anyone._attr_is_on is False and who._attr_is_on is False            # both are up: the usual clear-after (none here) applies
    assert anyone._attr_extra_state_attributes["asleep"] is True              # the attribute still follows the helper


def test_inputs_on_and_door_closed():
    states = {"binary_sensor.m": "on", "media_player.tv": "paused", "binary_sensor.n": "unavailable"}
    assert rooms.inputs_on(list(states), states.get) == ["binary_sensor.m"]
    assert [rooms.door_closed(s) for s in ("off", "closed", "on", "open", "unavailable", None)] == [True, True, False, False, None, None]


def test_a_number_past_a_threshold_is_an_input():
    z = {"entity_id": "X", "inputs": "sensor.tv_power>20, sensor.lux<5 sensor.p>= sensor.sextant_x_occupancy>1 binary_sensor.d>3", "door": "binary_sensor.d"}
    assert rooms.room_options(z)["inputs"] == ["sensor.tv_power>20", "sensor.lux<5"]
    states = {"sensor.tv_power": "85.5", "sensor.lux": "12", "sensor.dead": "unavailable", "sensor.nan": "nan"}
    specs = ["sensor.tv_power>20", "sensor.lux<5", "sensor.lux<=12", "sensor.dead>1", "sensor.nan>1", "sensor.gone<9", "sensor.tv_power>=85.5"]
    assert rooms.inputs_on(specs, states.get) == ["sensor.tv_power>20", "sensor.lux<=12", "sensor.tv_power>=85.5"]
    assert rooms.room_options({"inputs": "sensor.p >= -20, sensor.q  <  5"})["inputs"] == ["sensor.p>=-20", "sensor.q<5"]
    assert rooms.inputs_on(["sensor.p<" + "9" * 400], {"sensor.p": "3"}.get) == [], "an infinite limit is no test"


def _st(state, hours_ago, now=1_000_000.0):
    from datetime import datetime, timezone
    return types.SimpleNamespace(state=state, last_changed=datetime.fromtimestamp(now - hours_ago * 3600, timezone.utc))


def test_sensor_problems_name_missing_gone_and_stuck_sensors_once():
    now = 1_000_000.0
    keys = [{"floor": "G", "room": "Office", "inputs": ["binary_sensor.mm", "sensor.power>20", "binary_sensor.ok", "media_player.tv", "binary_sensor.typo", "sensor.p>1", "sensor.p<9"], "door": "binary_sensor.door"},
            {"floor": "G", "room": "Den", "inputs": ["binary_sensor.mm"], "door": None}]
    states = {"binary_sensor.mm": _st("on", 30), "sensor.power": _st("90", 100), "binary_sensor.ok": _st("on", 2),
              "media_player.tv": _st("playing", 90), "binary_sensor.door": _st("unavailable", 7)}
    bad = {"binary_sensor.typo": now - 7 * 3600, "sensor.p": now - 7 * 3600}
    found = rooms.sensor_problems(keys, states.get, now, 24 * 3600, 6 * 3600, bad)
    assert found == {"binary_sensor.mm": {"kind": "stuck", "age": 30 * 3600.0, "rooms": ["Office (G)", "Den (G)"]},
                     "binary_sensor.typo": {"kind": "missing", "age": 7 * 3600.0, "rooms": ["Office (G)"]},
                     "sensor.p": {"kind": "missing", "age": 7 * 3600.0, "rooms": ["Office (G)"]},
                     "binary_sensor.door": {"kind": "gone", "age": 7 * 3600.0, "rooms": ["Office (G)"]}}
    states["binary_sensor.door"] = _st("off", 100)   # a door shut for days is normal
    assert "binary_sensor.door" not in rooms.sensor_problems(keys, states.get, now, 24 * 3600, 6 * 3600, bad)
    states["binary_sensor.door"] = _st("unavailable", 1)   # a blip is not a repair
    assert "binary_sensor.door" not in rooms.sensor_problems(keys, states.get, now, 24 * 3600, 6 * 3600, bad)


def test_missing_needs_time_and_unavailable_then_unknown_keeps_counting():
    now, keys = 1_000_000.0, [{"floor": "G", "room": "R", "inputs": ["binary_sensor.late"], "door": None}]
    states, bad = {}, {}
    assert rooms.sensor_problems(keys, states.get, now, 99, 6 * 3600, bad) == {}, "first seen missing: the clock starts"
    assert "binary_sensor.late" in rooms.sensor_problems(keys, states.get, now + 7 * 3600, 99, 6 * 3600, bad)
    states["binary_sensor.late"] = _st("on", 0, now + 7 * 3600)   # it came up: clock forgotten
    assert rooms.sensor_problems(keys, states.get, now + 7 * 3600, 99 * 3600, 6 * 3600, bad) == {} and not bad
    states["binary_sensor.late"] = _st("unavailable", 7, now)
    rooms.sensor_problems(keys, states.get, now - 7 * 3600, 99, 6 * 3600, bad)   # unavailable since 7 h ago
    states["binary_sensor.late"] = _st("unknown", 0, now)                         # flips to unknown just now
    assert rooms.sensor_problems(keys, states.get, now, 99, 6 * 3600, bad)["binary_sensor.late"]["kind"] == "gone"


def test_a_media_player_that_is_unavailable_is_not_gone_but_a_missing_one_is():
    now, keys = 1_000_000.0, [{"floor": "G", "room": "R", "inputs": ["media_player.tv", "media_player.typo"], "door": None}]
    states, bad = {"media_player.tv": _st("unavailable", 48, now), "media_player.old": _st("unknown", 48, now)}, {"media_player.typo": now - 7 * 3600}
    assert rooms.sensor_problems(keys, states.get, now, 99, 6 * 3600, bad) == {"media_player.typo": {"kind": "missing", "age": 7 * 3600.0, "rooms": ["R (G)"]}}
    keys = [{"floor": "G", "room": "R", "inputs": ["media_player.tv"], "door": None}]
    bad = {"media_player.tv": now - 7 * 3600}                      # it was missing for 7 h, then came back as unknown
    assert rooms.sensor_problems(keys, states.get, now, 99, 6 * 3600, bad) == {} and not bad, "no stale clock is kept"
    states.clear()                                                 # and goes missing again: a fresh grace period
    assert rooms.sensor_problems(keys, states.get, now, 99, 6 * 3600, bad) == {} and bad == {"media_player.tv": now}


def test_a_closed_door_holds_someone_who_stays_but_not_someone_who_left():
    # shut in: still reading in the room 90 s after the door closed, then gone quiet
    s = rooms.settle(None, True, 0.0, door=False)
    s = rooms.settle(s, True, 10.0, door=True)
    assert not s["door_hold"]
    s = rooms.settle(s, True, 100.0, door=True)
    assert s["door_hold"]
    s = rooms.settle(s, False, 5000.0, door=True)               # asleep, BLE quiet
    assert s["on"] is True and s["state"] != "clear"
    s = rooms.settle(s, False, 5010.0, door=False)              # the door opens: back to the hold rules
    assert s["on"] is False
    # shut the door on the way out: stops reading before the wait is up
    s = rooms.settle(None, True, 0.0, door=False)
    s = rooms.settle(s, True, 10.0, door=True)
    s = rooms.settle(s, False, 40.0, door=True)
    s = rooms.settle(s, True, 200.0, door=True)                  # a stray reading later does not shut them in
    assert not s["door_hold"] and s["on"]
    s = rooms.settle(s, False, 210.0, door=True)
    assert s["on"] is False
    # a door that never opens lets go after door_max_s
    s = rooms.settle(None, True, 0.0, door=True, door_max_s=1000.0)
    s = rooms.settle(s, True, 100.0, door=True, door_max_s=1000.0)
    s = rooms.settle(s, False, 500.0, door=True, door_max_s=1000.0)
    assert s["on"]
    s = rooms.settle(s, False, 1200.0, door=True, door_max_s=1000.0)
    assert not s["on"]
    # an unknown door does nothing
    assert rooms.settle(rooms.settle(None, True, 0.0, door=None), False, 500.0, door=None)["on"] is False


def test_publish_rooms_uses_a_rooms_own_timing_inputs_and_door(hass):
    layout = {"floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [
        {"entity_id": "Kitchen", "room_hold_secs": 600, "inputs": "binary_sensor.kitchen_motion", "door": "binary_sensor.kitchen_door",
         "cords": [{"x": 0, "y": 0}] * 3}]}]}
    _added(hass)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"] = {}
    key = ("Ground Floor", "Kitchen")
    states = {"binary_sensor.kitchen_motion": "on", "binary_sensor.kitchen_door": "off"}
    hass.states = type("S", (), {"get": staticmethod(lambda e: type("St", (), {"state": states[e]})() if e in states else None)})()
    hass.data["sextant_room_answers"] = {key: (False, None)}
    sextant._publish_rooms(hass)
    sensor = hass.data["sextant_room_sensors"][key]
    assert sensor._attr_is_on is True                               # nothing BLE here: the motion sensor is the evidence
    assert sensor._attr_extra_state_attributes["inputs"] == ["binary_sensor.kitchen_motion"]
    states["binary_sensor.kitchen_motion"] = "off"
    sextant._publish_rooms(hass)
    attrs = sensor._attr_extra_state_attributes
    assert sensor._attr_is_on is True and attrs["hold_over"] is True   # its own 600 s hold, the global is 0


def test_people_sensor_ignores_a_pets_tag_but_not_a_person_or_a_sensor(hass):
    layout = {"floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [
        {"entity_id": "Kitchen", "inputs": "binary_sensor.kitchen_motion", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    _added(hass)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"] = {}
    key = ("Ground Floor", "Kitchen")
    states = {"binary_sensor.kitchen_motion": "off"}
    hass.states = type("S", (), {"get": staticmethod(lambda e: type("St", (), {"state": states[e]})() if e in states else None)})()
    anyone, people = hass.data["sextant_room_sensors"][key], hass.data["sextant_room_people"][key]
    assert (anyone.icon, people.icon) == ("mdi:map-marker-radius-outline", "mdi:account-outline")
    assert people.entity_id == "binary_sensor.kitchen_sextant_people_occupancy"
    assert people._attr_unique_id == "sextant_room_people_" + anyone._attr_unique_id[len("sextant_room_occupancy_"):]

    def answer(humans, count):
        hass.data["sextant_room_answers"] = {key: (count > 0, {"room": "Kitchen", "floor": "Ground Floor", "count": count, "humans": humans,
                                                              "people": [], "pets": ["Fry"], "things": []})}
        sextant._publish_rooms(hass)
    answer(0, 1)                                                    # only the cat's tag
    assert anyone._attr_is_on is True and people._attr_is_on is False
    answer(1, 2)
    assert people._attr_is_on is True
    answer(0, 1)
    people.memory = None
    states["binary_sensor.kitchen_motion"] = "on"                   # a motion sensor cannot tell: it counts as people
    answer(0, 1)
    assert people._attr_is_on is True
    states["binary_sensor.kitchen_motion"] = "off"                  # evidence gone, no hold set: it clears, the cat does not keep it on
    answer(0, 1)
    assert people._attr_is_on is False and anyone._attr_is_on is True
    answer(0, 2)                                                    # a named person with no tag row yet still counts
    hass.data["sextant_room_answers"][key][1]["people"] = ["David"]
    sextant._publish_rooms(hass)
    assert people._attr_is_on is True


def test_a_room_that_was_on_stays_on_over_a_restart_until_the_grace_runs_out(hass):
    import asyncio
    import types
    layout = {"floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [{"entity_id": "Kitchen", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    _added(hass)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"] = {}
    key = ("Ground Floor", "Kitchen")
    for s in (hass.data["sextant_room_sensors"][key], hass.data["sextant_room_people"][key]):
        s.hass = hass
        s.async_write_ha_state = lambda: None
        s._test_last_state = types.SimpleNamespace(state="on", attributes={})
        asyncio.run(s.async_added_to_hass())
    anyone, people = hass.data["sextant_room_sensors"][key], hass.data["sextant_room_people"][key]
    assert anyone._attr_is_on and people._attr_is_on        # carried over, nothing placed yet
    assert anyone._attr_extra_state_attributes["sources"] == ["restored"]
    hass.states = type("S", (), {"get": staticmethod(lambda e: None)})()
    hass.data["sextant_room_answers"] = {}
    sextant._publish_rooms(hass)
    assert anyone._attr_is_on is True and people._attr_is_on is True
    anyone.restore_until = people.restore_until = 1.0       # grace over
    sextant._publish_rooms(hass)
    assert anyone._attr_is_on is False and people._attr_is_on is False
    # a reload after the deadline gets no new grace; the sensors' own memory was never fed by it
    hass.data["sextant_restore_deadline"] = 1.0
    anyone._attr_is_on = False
    anyone._test_last_state = types.SimpleNamespace(state="on", attributes={})
    asyncio.run(anyone.async_added_to_hass())
    assert anyone._attr_is_on is False and not getattr(anyone, "restore_until", 0)


def test_a_door_hold_survives_a_restart_and_lets_go_when_the_door_opens(hass):
    import asyncio
    import types
    layout = {"floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [{"entity_id": "Bedroom", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    _added(hass)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"] = {}
    key = ("Ground Floor", "Bedroom")
    anyone = hass.data["sextant_room_sensors"][key]
    anyone.hass = hass
    anyone.async_write_ha_state = lambda: None
    anyone._test_last_state = types.SimpleNamespace(state="on", attributes={"door_hold": True})
    asyncio.run(anyone.async_added_to_hass())
    hass.states = type("S", (), {"get": staticmethod(lambda e: None)})()
    hass.data["sextant_room_answers"] = {}
    sextant._publish_rooms(hass)
    assert anyone.memory["door_hold"] is True and anyone.memory["on"] is True
    anyone.restore_until = 1.0                              # grace over: the door hold still keeps the room on
    sextant._publish_rooms(hass)
    assert anyone._attr_is_on is True and anyone._attr_extra_state_attributes["sources"] == ["door"]


def _restart_bedroom(hass, attrs, door_state=None, answers=None):
    import asyncio
    import types
    layout = {"floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [{"entity_id": "Bedroom", "cords": [{"x": 0, "y": 0}] * 3}]}]}
    _added(hass)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_room_keys"][0]["door"] = "binary_sensor.door" if door_state else None
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"] = {}
    key = ("Ground Floor", "Bedroom")
    anyone = hass.data["sextant_room_sensors"][key]
    anyone.hass = hass
    anyone.async_write_ha_state = lambda: None
    anyone._test_last_state = types.SimpleNamespace(state="on", attributes=attrs)
    asyncio.run(anyone.async_added_to_hass())
    st = types.SimpleNamespace(state=door_state)
    hass.states = type("S", (), {"get": staticmethod(lambda e: st if door_state else None)})()
    hass.data["sextant_room_answers"] = answers or {}
    anyone.restore_until = 1.0
    return anyone, key


def test_a_restart_does_not_renew_the_door_hold_timeout(hass):
    import time
    anyone, _ = _restart_bedroom(hass, {"door_hold": True, "door_at": time.time() - 10 ** 6})
    sextant._publish_rooms(hass)
    assert anyone.memory["door_hold"] is False and anyone._attr_is_on is False


def test_an_open_door_after_a_restart_ends_the_door_hold(hass):
    anyone, _ = _restart_bedroom(hass, {"door_hold": True}, door_state="on")
    sextant._publish_rooms(hass)
    assert anyone.memory["door_hold"] is False and anyone._attr_is_on is False


def test_a_restored_door_hold_lets_go_when_its_people_are_elsewhere(hass):
    anyone, key = _restart_bedroom(hass, {"door_hold": True, "door_people": ["David"]}, door_state="off",
                                   answers={("Ground Floor", "Kitchen"): (True, {"people": ["David"]})})
    sextant._publish_rooms(hass)
    assert anyone.memory["door_hold"] is False and anyone._attr_is_on is False


def test_sources_say_why_a_room_is_on():
    assert rooms.sources(True, False, [], False, False, False, False) == ["bluetooth"]
    assert rooms.sources(False, False, ["media_player.tv", "binary_sensor.m"], False, False, False, False) == ["media_player", "sensor"]
    assert rooms.sources(False, True, [], True, True, True, True) == ["radar", "forced", "door", "restored", "hold"]
    assert rooms.sources(False, False, [], False, False, False, False) == []


def test_inputs_never_include_our_own_sensors_or_the_door():
    o = rooms.room_options({"inputs": "binary_sensor.kitchen_sextant_occupancy, binary_sensor.door, binary_sensor.m", "door": "binary_sensor.door"})
    assert o["inputs"] == ["binary_sensor.m"]


def test_an_unavailable_door_keeps_a_hold_and_a_departure_releases_it():
    s = rooms.settle(None, True, 0.0, door=True)
    s = rooms.settle(s, True, 100.0, door=True)
    assert s["door_hold"]
    s = rooms.settle(s, False, 200.0, door=None)                 # contact sensor flaps unavailable
    assert s["door_hold"] and s["on"]
    assert rooms.release_if_elsewhere(s, ["Eilee"], {"Eilee", "Jack"}) and not s["door_hold"]
    assert not rooms.settle(s, False, 300.0, door=True)["on"]    # and it does not take hold again
    s = rooms.settle(None, True, 0.0, door=True)
    s = rooms.settle(s, True, 100.0, door=True)
    assert not rooms.release_if_elsewhere(s, ["Eilee", "Jack"], {"Eilee"})   # one of them is still unaccounted for


def test_review_two_fixes_in_rooms():
    # a hold whose contact sensor went unavailable still ends at door_max_s
    s = rooms.settle(None, True, 0.0, door=True)
    s = rooms.settle(s, True, 100.0, door=True)
    assert rooms.settle(s, False, 200.0, door=None)["door_hold"]
    assert not rooms.settle(s, False, 100.0 + 29000.0, door=None)["door_hold"]
    # no Sextant occupancy sensor (room, floor or house) and no malformed id is an input
    o = rooms.room_options({"inputs": "binary_sensor.sextant_house_occupancy, binary_sensor.a_sextant_floor_occupancy, binary_sensor._motion, binary_sensor.ok"})
    assert o["inputs"] == ["binary_sensor.ok"]


def test_room_inputs_drop_suffixed_sextant_occupancy_entities():
    zone = {"inputs": ["binary_sensor.den_sextant_people_occupancy_2", "binary_sensor.motion"]}
    assert rooms.room_options(zone)["inputs"] == ["binary_sensor.motion"]


def test_household_floor_names_a_floor_only_when_everyone_home_is_on_it():
    assert rooms.household_floor(["Alex", "Robin"], {"Alex": "Up", "Robin": "Up"}) == ("Up", {"floors": {"Up": ["Alex", "Robin"]}, "unplaced": []})
    assert rooms.household_floor(["Alex", "Robin"], {"Alex": "Up", "Robin": "Down"})[0] == "mixed"
    # Robin is home but on no floor (lost, outside, Wi-Fi only): not "everyone is Up".
    assert rooms.household_floor(["Alex", "Robin"], {"Alex": "Up"}) == ("unknown", {"floors": {"Up": ["Alex"]}, "unplaced": ["Robin"]})
    # Someone placed but not home (a pet, a stale row) has no say.
    assert rooms.household_floor(["Alex"], {"Alex": "Up", "Meg": "Down"})[0] == "Up"
    assert rooms.household_floor([], {}) == ("away", {"floors": {}, "unplaced": []})


def test_sensor_clocks_outlive_a_restart():
    """last_changed starts again with Home Assistant; the saved clocks do not."""
    from datetime import datetime, timezone
    from sextant import runtime
    now = 1_000_000.0
    keys = [{"floor": "G", "room": "R", "inputs": ["binary_sensor.mm", "binary_sensor.dead"], "door": None}]
    bad, on = {}, {}
    states = {"binary_sensor.mm": _st("on", 30), "binary_sensor.dead": _st("unavailable", 0)}
    rooms.sensor_problems(keys, states.get, now - 7 * 3600, 24 * 3600, 6 * 3600, bad, on)
    saved = json.loads(json.dumps(runtime.snapshot(now - 60, sensors={"bad": bad, "on": {e: v[0] for e, v in on.items()}})))
    back = runtime.restore(saved, now)["sensors"]
    assert back == {"bad": {"binary_sensor.dead": now - 7 * 3600}, "on": {"binary_sensor.mm": now - 30 * 3600}}
    back["on"] = {e: [t, None] for e, t in back["on"].items()}   # as the integration hands them back
    # Restarted a minute ago: unavailable while it starts, then on again with a new last_changed.
    assert rooms.sensor_problems(keys, {"binary_sensor.dead": _st("unavailable", 0)}.get, now, 24 * 3600, 6 * 3600, back["bad"], back["on"]).keys() == {"binary_sensor.dead"}
    found = rooms.sensor_problems(keys, {"binary_sensor.mm": _st("on", 0), "binary_sensor.dead": _st("unknown", 0)}.get, now, 24 * 3600, 6 * 3600, back["bad"], back["on"])
    assert found["binary_sensor.mm"] == {"kind": "stuck", "age": 30 * 3600.0, "rooms": ["R (G)"]} and found["binary_sensor.dead"]["kind"] == "gone"
    # Off and on again between two calls is a new spell, not the old one.
    later = {"binary_sensor.mm": types.SimpleNamespace(state="on", last_changed=datetime.fromtimestamp(now + 50, timezone.utc))}
    assert "binary_sensor.mm" not in rooms.sensor_problems(keys, later.get, now + 60, 24 * 3600, 6 * 3600, back["bad"], back["on"])
    # Off ends the clock; so does a restart too long to vouch for the gap.
    rooms.sensor_problems(keys, {"binary_sensor.mm": _st("off", 0)}.get, now, 24 * 3600, 6 * 3600, back["bad"], back["on"])
    assert back["on"] == {}
    assert runtime.restore(saved, now + 2 * 3600)["sensors"] == {"bad": {}, "on": {}}


def test_a_room_keeps_its_since_over_a_restart(hass):
    import asyncio
    import time
    import types
    from datetime import datetime, timezone
    layout = {"floor": [{"name": "Ground Floor", "floor_id": "ground", "zones": [
        {"entity_id": n, "cords": [{"x": 0, "y": 0}] * 3} for n in ("Kitchen", "Office", "Hall")]}]}
    _added(hass)
    hass.data["sextant_room_keys"] = rooms.room_keys(layout)
    hass.data["sextant_aggregate_sensors"] = {}
    platform.ensure_room_sensors(hass, layout)
    hass.data["sextant_room_switches"] = {}
    then = time.time() - 3600
    iso = datetime.fromtimestamp(then, timezone.utc).isoformat(timespec="seconds")
    was = {"Kitchen": "on", "Office": "on", "Hall": "off"}
    sensors = {n: hass.data["sextant_room_sensors"][("Ground Floor", n)] for n in was}
    for n, s in sensors.items():
        s.hass = hass
        s.async_write_ha_state = lambda: None
        s._test_last_state = types.SimpleNamespace(state=was[n], attributes={"since": iso})
        asyncio.run(s.async_added_to_hass())
    hass.states = type("S", (), {"get": staticmethod(lambda e: None)})()

    def shown(n):
        a = sensors[n]._attr_extra_state_attributes
        return sensors[n]._attr_is_on, a["state"], datetime.fromisoformat(a["since"]).timestamp()
    hass.data["sextant_room_answers"] = {}
    sextant._publish_rooms(hass)                      # nothing placed yet: the restored states show, with their since
    assert shown("Kitchen") == (True, "extended", int(then)) and shown("Hall") == (False, "clear", int(then))
    hass.data["sextant_room_answers"] = {("Ground Floor", "Kitchen"): (True, None)}
    sextant._publish_rooms(hass)                      # the kitchen is confirmed: still the long stay it was
    sextant._publish_rooms(hass)
    assert shown("Kitchen") == (True, "extended", int(then))
    sensors["Office"].restore_until = 1.0             # the office never was: it cleared now, not an hour ago
    sextant._publish_rooms(hass)
    assert shown("Office")[:2] == (False, "clear") and shown("Office")[2] > then + 3000
    assert shown("Hall") == (False, "clear", int(then))


def test_a_dog_whose_collar_says_home_is_a_pet_at_home():
    assert rooms.people_home({"Meg": "gps"}, pets={"Meg"})[1]["pets_home"] == ["Meg"]
