"""Wi-Fi association (wifi.py): candidates, footprints, matching, the floor hint."""
import sextant  # noqa: F401
from sextant import persons, wifi


def _states():
    return [
        ("device_tracker.iphone", "home", {"source_type": "router", "mac": "aa:bb:cc:00:04:91", "ap_mac": "aa:bb:cc:00:01:01", "friendly_name": "iPhone"}),
        ("device_tracker.alex_s_phone", "home", {"source_type": "router", "mac": "AA:BB:CC:00:04:91", "ap_mac": None, "friendly_name": "Alex's Phone"}),
        ("device_tracker.watch", "not_home", {"source_type": "router", "mac": "aa:bb:cc:00:05:b4", "ap_mac": None, "friendly_name": "Watch"}),
        ("device_tracker.kitchen_e7", "home", {"source_type": "router", "mac": "aa:bb:cc:00:01:01", "ap_mac": None, "friendly_name": "Kitchen E7"}),
        ("device_tracker.alex_phone", "home", {"source_type": "gps", "latitude": 51.5, "longitude": -0.1}),
        ("device_tracker.alex_smith_sextant", "home", {"source_type": "bluetooth_le"}),
        ("sensor.not_a_tracker", "home", {"source_type": "router", "ap_mac": "x"}),
    ]


def test_candidates_are_router_trackers_with_an_access_point_minus_the_access_points_themselves():
    c = wifi.candidates(_states(), ap_macs=["AA:BB:CC:00:01:01"])
    assert set(c) == {"device_tracker.iphone", "device_tracker.watch"}
    # The stale duplicate's better name is kept with the live tracker.
    assert c["device_tracker.iphone"] == {"name": "Alex's Phone", "home": True, "ap": "aa:bb:cc:00:01:01", "mac": "aa:bb:cc:00:04:91", "ssid": None}
    assert wifi.better_name("iPhone iPhone", "iPhone") == "iPhone" and wifi.tidy({"name": "Watch Watch"})["name"] == "Watch"
    assert c["device_tracker.watch"]["home"] is False and c["device_tracker.watch"]["ap"] is None


def test_a_client_once_seen_on_an_access_point_stays_a_candidate_when_away():
    """UniFi drops ap_mac from a client that is away; the store remembers the client."""
    known = {}
    home = [("device_tracker.iphone", "home", {"source_type": "router", "mac": "aa:bb:cc:00:04:91", "ap_mac": "8c:ed", "friendly_name": "iPhone"})]
    assert set(wifi.candidates(home, known=known)) == {"device_tracker.iphone"} and known == {"device_tracker.iphone": {"mac": "aa:bb:cc:00:04:91"}}
    away = [("device_tracker.iphone", "not_home", {"source_type": "router", "mac": "aa:bb:cc:00:04:91", "friendly_name": "iPhone"}),
            ("device_tracker.never", "not_home", {"source_type": "router", "mac": "aa:bb", "friendly_name": "Something"})]
    c = wifi.candidates(away, known=known)
    assert set(c) == {"device_tracker.iphone"} and c["device_tracker.iphone"]["home"] is False and c["device_tracker.iphone"]["ap"] is None
    assert wifi.candidates(away) == {}                       # without the memory, nothing


def test_nobody_eligible_means_no_owner():
    store = wifi.new_store()
    for _ in range(wifi.MATCH_MIN_CYCLES):
        wifi.match_update(store, "device_tracker.x", "person.meg", 1.0)
    assert wifi.suggest(store, "device_tracker.x", {}) == (None, 0.0, "nobody")


def test_the_footprint_learns_and_is_trusted_only_with_enough_cycles():
    store = wifi.new_store()
    ap = "aa:bb:cc:00:07:5b"
    assert wifi.floor_odds(store, ap, "Ground Floor") == {"Ground Floor": 1.0}      # the access point's own floor stands in
    assert wifi.best_place(store, ap, ("Ground Floor", "Sewing Room")) == ("Ground Floor", "Sewing Room")
    for _ in range(30):
        wifi.footprint_update(store, ap, "Ground Floor", "Sewing Room")
    for _ in range(20):
        wifi.footprint_update(store, ap, "Second Floor", "Robin Room")
    odds = wifi.floor_odds(store, ap, "Ground Floor")
    assert odds == {"Ground Floor": 0.6, "Second Floor": 0.4}
    assert wifi.best_place(store, ap) == ("Ground Floor", "Sewing Room")
    # The hint: the floor it most means keeps its score, the other loses in proportion.
    assert wifi.floor_factor(odds, "Ground Floor", 0.25) == 1.0
    assert abs(wifi.floor_factor(odds, "Second Floor", 0.25) - (1 - 0.25 * (1 - 0.4 / 0.6))) < 1e-9
    assert wifi.floor_factor(odds, "Basement", 0.25) == 0.75
    assert wifi.floor_factor(None, "Basement", 0.25) == 1.0 and wifi.floor_factor(odds, "Basement", 0.0) == 1.0


def test_footprint_counts_are_capped_not_unbounded():
    store = wifi.new_store()
    for _ in range(int(wifi.FOOTPRINT_CAP) + 10):
        wifi.footprint_update(store, "ap", "F", "R")
    assert sum(store["aps"]["ap"]["floors"].values()) < wifi.FOOTPRINT_CAP


def test_a_tracker_is_matched_by_name_or_by_who_it_agrees_with():
    store = wifi.new_store()
    store["names"] = {"device_tracker.alex_s_phone": "Alex's Phone", "device_tracker.iphone_2": "iPhone"}
    names = {"person.alex_smith": "Alex Smith", "person.robin_smith": "Robin Smith"}
    assert wifi.suggest(store, "device_tracker.alex_s_phone", names) == ("person.alex_smith", 1.0, "name")
    # Whole words only, and one person only.
    store["names"].update({"device_tracker.brian": "Brian's iPad", "device_tracker.two": "Alex Phone"})
    assert wifi.suggest(store, "device_tracker.brian", {"person.ian": "Ian Smith"})[2] == "learning"
    assert wifi.suggest(store, "device_tracker.two", {"person.a": "Alex A", "person.b": "Alex B"})[2] == "learning"
    assert wifi.suggest(store, "device_tracker.iphone_2", names) == (None, 0.0, "learning")
    for _ in range(wifi.MATCH_MIN_CYCLES):
        wifi.match_update(store, "device_tracker.iphone_2", "person.robin_smith", 1.0)
        wifi.match_update(store, "device_tracker.iphone_2", "person.alex_smith", 0.0)
    person, conf, why = wifi.suggest(store, "device_tracker.iphone_2", names)
    assert person == "person.robin_smith" and why == "co-location" and conf == 1.0
    # A score kept for someone who is not a candidate owner (a pet) is not in the ranking.
    for _ in range(wifi.MATCH_MIN_CYCLES):
        wifi.match_update(store, "device_tracker.iphone_2", "person.meg", 0.9)
    assert wifi.suggest(store, "device_tracker.iphone_2", names)[0] == "person.robin_smith"
    # Two people it agrees with about equally stay ambiguous.
    for _ in range(wifi.MATCH_MIN_CYCLES):
        wifi.match_update(store, "device_tracker.iphone_2", "person.alex_smith", 1.0)
        wifi.match_update(store, "device_tracker.iphone_2", "person.robin_smith", 0.0)
    assert wifi.suggest(store, "device_tracker.iphone_2", names)[2] == "ambiguous"


def test_agreement_tells_people_apart_by_who_is_home():
    assert wifi.agreement(True, True, True) == 1.0          # both home, same floor
    assert wifi.agreement(True, True, False) == 0.5         # both home, the access point's floor is not theirs (a wall unit under a bedroom)
    assert wifi.agreement(True, True, None) == 1.0          # no floor known for the access point yet
    assert wifi.agreement(False, False, None) == 1.0        # both away
    assert wifi.agreement(True, False, None) == 0.0 and wifi.agreement(False, True, True) == 0.0


def test_wifi_keeps_a_person_home_between_ble_and_gps():
    gps_away = {"entity": "device_tracker.t", "zone": "Hill College Dorm", "latitude": 51.6, "longitude": 0.0}
    w = {"entity": "device_tracker.iphone", "home": True, "ap": "aa:bb:cc:00:01:01", "ap_name": "Kitchen E7", "floor": "Ground Floor", "room": "Kitchen", "area_id": "kitchen", "floor_id": "ground"}
    assert persons.home_via("away", gps_away, w) == "wifi"
    assert persons.home_via("away", gps_away, {**w, "home": False}) is None
    assert persons.home_via("quiet", None, w) == "ble"                    # BLE first
    fix = persons.tracker_fix("away", gps_away, None, w)
    assert fix["location_name"] == "home" and fix["source_type"] == "router" and fix["source"] == "wifi" and fix["tracker"] == "device_tracker.iphone"
    out = persons.fuse(None, [], "away", None, gps_away, [], None, w)
    state, attrs = out["sextant_person_location"]
    assert state == "Kitchen" and attrs["source"] == "wifi" and attrs["kind"] == "room" and attrs["access_point"] == "Kitchen E7"
    assert attrs["zone"] == "Hill College Dorm"                              # the GPS side still rides along
    assert out["sextant_person_room"][0] == "Kitchen" and out["sextant_person_floor"][0] == "Ground Floor"
    # Not home on Wi-Fi: GPS as before.
    assert persons.fuse(None, [], "away", None, gps_away, [], None, {**w, "home": False})["sextant_person_location"][0] == "Hill College Dorm"


def test_stale_match_pairs_are_forgotten_and_the_table_is_bounded():
    store = wifi.new_store()
    wifi.match_update(store, "device_tracker.old", "person.gone", 1.0, now=0.0)
    wifi.match_update(store, "device_tracker.new", "person.here", 1.0, now=40 * 86400.0)
    assert wifi.prune_matches(store, 40 * 86400.0) == 1
    assert set(store["matches"]) == {"device_tracker.new"}
    for i in range(wifi.MATCH_MAX_PAIRS + 5):
        wifi.match_update(store, f"device_tracker.t{i}", "person.p", 1.0, now=1000.0 + i)
    wifi.prune_matches(store, 2000.0)
    assert sum(len(v) for v in store["matches"].values()) == wifi.MATCH_MAX_PAIRS
    assert "device_tracker.t0" not in store["matches"] and f"device_tracker.t{wifi.MATCH_MAX_PAIRS + 4}" in store["matches"]


# --- access points on the plan -------------------------------------------------

def test_norm_mac_accepts_dashes_and_case_and_rejects_the_rest():
    assert wifi.norm_mac("AA-BB-CC-00-07-5B") == "aa:bb:cc:00:07:5b"
    assert wifi.norm_mac(" aa:bb:cc:00:08:c6 ") == "aa:bb:cc:00:08:c6"
    assert wifi.norm_mac("8c:ed") is None and wifi.norm_mac(None) is None and wifi.norm_mac(42) is None


def test_access_points_are_the_hubs_uap_devices_named_as_home_assistant_names_them():
    raws = [
        {"type": "uap", "mac": "AA:BB:CC:00:01:01", "name": "Kitchen E7 ctrl", "model": "UAPA697", "num_sta": 12, "state": 1},
        {"type": "usw", "mac": "aa:bb:cc:00:09:72", "name": "Desk USW Flex Mini", "num_sta": 3, "state": 1},
        {"type": "uap", "mac": "aa:bb:cc:00:01:02", "name": "Garage U7-Pro", "num_sta": True, "state": 0},
        {"type": "uap", "mac": "aa:bb:cc:00:01:01", "name": "duplicate"},
        {"type": "uap", "mac": "not a mac", "name": "broken"},
        None, "junk",
    ]
    registry = {"aa:bb:cc:00:01:01": {"name": "Kitchen E7", "area_id": "kitchen"}, "aa:bb:cc:00:01:02": "junk"}
    aps = wifi.access_points(raws, registry)
    assert [a["mac"] for a in aps] == ["aa:bb:cc:00:01:02", "aa:bb:cc:00:01:01"]   # by name; switches left out
    garage, kitchen = aps
    assert kitchen == {"mac": "aa:bb:cc:00:01:01", "name": "Kitchen E7", "model": "UAPA697", "clients": 12, "online": True, "area_id": "kitchen"}
    # A bool is not a client count, and a disconnected device is offline.
    assert garage["clients"] is None and garage["online"] is False and garage["area_id"] is None and garage["name"] == "Garage U7-Pro"
    assert wifi.access_points(None) == [] and wifi.access_points([{"type": "uap", "mac": "aa:bb:cc:dd:ee:ff"}], None)[0]["name"] == "aa:bb:cc:dd:ee:ff"


def test_placed_access_points_first_placement_wins_and_bad_entries_are_skipped():
    layout = {"floor": [
        {"name": "Ground", "access_points": [
            {"mac": "AA:BB:CC:00:01:01", "cords": {"x": 100, "y": 200.5}},
            {"mac": "aa:bb:cc:00:01:02", "cords": {"x": float("nan"), "y": 1}},
            {"mac": "aa:bb:cc:00:07:5b", "cords": {"x": True, "y": 1}},
            {"mac": None, "cords": {"x": 1, "y": 1}},
            "junk",
        ]},
        {"name": "Upstairs", "access_points": [{"mac": "aa:bb:cc:00:01:01", "cords": {"x": 5, "y": 5}}, {"mac": "aa:bb:cc:00:06:c6", "cords": {"x": 7, "y": 8}}]},
        {"access_points": [{"mac": "aa:bb:cc:00:08:c6", "cords": {"x": 1, "y": 1}}]},   # a floor without a name
    ]}
    assert wifi.placed_access_points(layout) == {
        "aa:bb:cc:00:01:01": {"floor": "Ground", "x": 100.0, "y": 200.5},
        "aa:bb:cc:00:06:c6": {"floor": "Upstairs", "x": 7.0, "y": 8.0},
    }
    assert wifi.placed_access_points(None) == {} and wifi.placed_access_points({"floor": None}) == {}


def _ap_layout():
    room = [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}, {"x": 0, "y": 100}]
    return {"floor": [{"name": "Ground", "zones": [{"entity_id": "Kitchen", "cords": room, "poly": True}],
                       "access_points": [{"mac": "aa:bb:cc:00:01:01", "name": "Kitchen E7", "cords": {"x": 50, "y": 50}},
                                         {"mac": "aa:bb:cc:00:01:02", "name": "Garage U7-Pro", "cords": {"x": 500, "y": 50}}]}]}


def test_a_placed_access_point_is_on_the_floor_and_in_the_room_it_was_placed_in():
    import sextant as core

    class Hass:   # no registries: the plan alone places them
        pass
    aps = core._wifi_access_points(Hass(), _ap_layout(), ["AA:BB:CC:00:01:01", "aa:bb:cc:00:01:02", "aa:bb:cc:00:07:5b"])
    assert aps["aa:bb:cc:00:01:01"] == {"name": "Kitchen E7", "floor": "Ground", "room": "Kitchen", "area_id": None, "floor_id": None, "placed": True}
    # Outside every room: the floor still counts.
    assert aps["aa:bb:cc:00:01:02"]["floor"] == "Ground" and aps["aa:bb:cc:00:01:02"]["room"] is None
    assert "aa:bb:cc:00:07:5b" not in aps   # not placed, and no registry to place it by
    assert core._wifi_access_points(Hass(), _ap_layout(), []) == {}


def test_unifi_access_points_reads_every_hub_and_survives_one_not_set_up():
    import types

    import sextant as core

    dev = lambda raw: types.SimpleNamespace(raw=raw)   # noqa: E731
    hub = types.SimpleNamespace(api=types.SimpleNamespace(devices={"a": dev({"type": "uap", "mac": "aa:bb:cc:00:01:01", "name": "Kitchen E7", "num_sta": 4, "state": 1}),
                                                                   "b": dev({"type": "usw", "mac": "aa:bb:cc:00:09:72", "name": "Switch"})}))
    entries = [types.SimpleNamespace(runtime_data=hub), types.SimpleNamespace(runtime_data=None), types.SimpleNamespace()]

    class Hass:
        config_entries = types.SimpleNamespace(async_entries=lambda domain: entries if domain == "unifi" else [])
    aps = core._unifi_access_points(Hass())
    assert [(a["mac"], a["name"], a["clients"]) for a in aps] == [("aa:bb:cc:00:01:01", "Kitchen E7", 4)]

    # No hub set up (no integration, or still starting): not known, rather
    # than a controller with no access points.
    entries[:] = [types.SimpleNamespace(runtime_data=None)]
    assert core._unifi_access_points(Hass()) is None
    entries[:] = [types.SimpleNamespace(runtime_data=types.SimpleNamespace(api=types.SimpleNamespace(devices={})))]
    assert core._unifi_access_points(Hass()) == []


def test_a_hyphenated_ap_mac_matches_the_access_point_placed_on_the_plan():
    import sextant as core

    states = [("device_tracker.iphone", "home", {"source_type": "router", "mac": "AA-BB-CC-00-04-91", "ap_mac": "AA-BB-CC-00-01-01", "friendly_name": "iPhone"})]
    c = wifi.candidates(states, ap_macs=["aa:bb:cc:00:01:01"])
    assert c["device_tracker.iphone"]["ap"] == "aa:bb:cc:00:01:01" and c["device_tracker.iphone"]["mac"] == "aa:bb:cc:00:04:91"

    class Hass:
        pass
    aps = core._wifi_access_points(Hass(), _ap_layout(), [c["device_tracker.iphone"]["ap"], "AA-BB-CC-00-01-02"])
    assert aps["aa:bb:cc:00:01:01"]["room"] == "Kitchen" and aps["aa:bb:cc:00:01:02"]["placed"] is True


def test_wifi_cycle_candidates_match_a_second_pass_with_the_access_points_ruled_out():
    import types

    import sextant as core

    states = _states() + [("device_tracker.e7_switch", "home", {"source_type": "router", "mac": "aa:bb:cc:00:01:01", "ap_mac": "aa:bb:cc:00:01:02", "friendly_name": "E7"})]
    st = [types.SimpleNamespace(entity_id=e, state=s, attributes=a) for e, s, a in states]

    class Hass:
        class states:  # noqa: N801
            @staticmethod
            def async_all(domain):
                return st

            @staticmethod
            def get(_entity):
                return None
    store = core._wifi_store
    store["clients"] = {}
    view = core._wifi_cycle(Hass(), _ap_layout(), {})
    infra = {c["ap"] for c in wifi.candidates(states, known={}).values() if c.get("ap")}
    assert view["candidates"] == wifi.candidates(states, infra, {})
    assert "device_tracker.e7_switch" not in view["candidates"] and "device_tracker.iphone" in view["candidates"]


def test_wifi_access_points_are_remembered_until_the_layout_version_moves(monkeypatch):
    import sextant as core

    class Hass:
        pass
    calls = []
    real = core._wifi_access_points_uncached
    monkeypatch.setattr(core, "_wifi_access_points_uncached", lambda *a: calls.append(1) or real(*a))
    version = [1]
    monkeypatch.setattr(core, "get_layout_version", lambda _h: version[0])
    core._wifi_ap_cache.update(key=None, at=0.0, out=None)
    macs = ["aa:bb:cc:00:01:01"]
    first = core._wifi_access_points(Hass(), _ap_layout(), macs)
    first["aa:bb:cc:00:01:01"]["name"] = "mutated"
    again = core._wifi_access_points(Hass(), _ap_layout(), macs)
    assert len(calls) == 1 and again["aa:bb:cc:00:01:01"]["name"] == "Kitchen E7"
    core._wifi_access_points(Hass(), _ap_layout(), macs + ["aa:bb:cc:00:01:02"])
    version[0] = 2
    core._wifi_access_points(Hass(), _ap_layout(), macs)
    assert len(calls) == 3
