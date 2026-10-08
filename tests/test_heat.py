"""The Wi-Fi signal map (heat.py) and its collector."""
import math
import types

import sextant  # noqa: F401
from sextant import heat

SCALE = 100.0   # px per metre: a cell is 100 px across
KITCHEN, GARAGE = "8c:ed:e1:00:de:ed", "28:70:4e:27:04:ed"


def test_cells_are_a_metre_square_on_the_floors_scale():
    assert heat.cell_index(150, 99, SCALE) == (1, 0)
    assert heat.cell_index(-1, 0, SCALE) == (-1, 0)
    assert heat.cell_index(1, 1, None) is None and heat.cell_index(float("nan"), 1, SCALE) is None


def test_samples_pool_per_cell_and_the_view_names_the_serving_access_point():
    s = heat.new_store()
    for dbm in (-50, -52, -54):
        assert heat.add(s, "Ground", 120, 130, SCALE, KITCHEN, dbm, "proxy", 0, reference=True)
    heat.add(s, "Ground", 140, 160, SCALE, GARAGE, -70, "proxy2", 0, reference=True)
    heat.add(s, "Ground", 900, 900, SCALE, KITCHEN, -60, "proxy3", 0, reference=True)   # one sample: not drawn
    heat.add(s, "Upstairs", 120, 130, SCALE, KITCHEN, -80, "proxy4", 0, reference=True)
    cells = heat.view(s, "Ground", SCALE)
    assert len(cells) == 1
    c = cells[0]
    assert (c["x"], c["y"], c["size"], c["n"], c["ap"]) == (100.0, 100.0, 100.0, 4, KITCHEN)
    assert c["dbm"] == -56.5 and c["aps"] == {KITCHEN: [-52.0, 3], GARAGE: [-70.0, 1]}
    assert heat.view(s, "Ground", None) == []


def test_readings_that_are_not_signal_levels_are_refused():
    s = heat.new_store()
    assert not heat.add(s, "Ground", 1, 1, SCALE, KITCHEN, 0, "c", 0)
    assert not heat.add(s, "Ground", 1, 1, SCALE, KITCHEN, float("nan"), "c", 0)
    assert not heat.add(s, "Ground", 1, 1, SCALE, None, -50, "c", 0)
    assert not heat.add(s, "", 1, 1, SCALE, KITCHEN, -50, "c", 0)
    assert s["cells"] == {}


def test_a_moving_client_learns_its_offset_from_the_proxies_in_the_cell():
    s = heat.new_store()
    for _ in range(5):
        heat.add(s, "Ground", 10, 10, SCALE, KITCHEN, -50, "proxy", 0, reference=True)
    # A watch reads 10 dB under the proxy, every time.
    for _ in range(200):
        heat.add(s, "Ground", 10, 10, SCALE, KITCHEN, -60, "watch", 0)
    off = s["bias"]["watch"]
    assert -10.5 < off < -8.5
    # Where there is no reference, its samples are corrected by what it learned.
    heat.add(s, "Ground", 510, 10, SCALE, KITCHEN, -70, "watch", 0)
    row = s["cells"]["Ground|5|0"]["aps"][KITCHEN]
    assert math.isclose(row[1] / row[0], -70 - off)
    # Offsets are bounded.
    for _ in range(500):
        heat.add(s, "Ground", 10, 10, SCALE, KITCHEN, -100, "pocket", 0)
    assert s["bias"]["pocket"] >= -heat.BIAS_MAX_DB


def test_counts_halve_at_the_cap_and_the_oldest_cells_go_past_the_limit(monkeypatch):
    s = heat.new_store()
    for _ in range(int(heat.CELL_CAP)):
        heat.add(s, "Ground", 10, 10, SCALE, KITCHEN, -50, "p", 0, reference=True)
    assert s["cells"]["Ground|0|0"]["aps"][KITCHEN] == [heat.CELL_CAP / 2, -50 * heat.CELL_CAP / 2, heat.CELL_CAP / 2, -50 * heat.CELL_CAP / 2]
    # A busy moving client ages the cell's samples, not the proxies' reference.
    for _ in range(int(heat.CELL_CAP)):
        heat.add(s, "Ground", 10, 10, SCALE, KITCHEN, -50, "phone", 0)
    assert s["cells"]["Ground|0|0"]["aps"][KITCHEN][2] == heat.CELL_CAP / 2
    monkeypatch.setattr(heat, "MAX_CELLS", 3)
    for i in range(5):
        heat.add(s, "Ground", 10 + 100 * (i + 1), 10, SCALE, KITCHEN, -50, "p", 10 + i, reference=True)
    assert sorted(s["cells"]) == ["Ground|3|0", "Ground|4|0", "Ground|5|0"]


def test_one_sample_per_client_every_half_minute():
    s = heat.new_store()
    assert heat.due(s, "c", 100)
    heat.add(s, "Ground", 10, 10, SCALE, KITCHEN, -50, "c", 100)
    assert not heat.due(s, "c", 120) and heat.due(s, "c", 130) and heat.due(s, "c", 50)   # a clock step back


def test_rooms_are_ranked_weakest_first_by_median():
    cells = [{"x": 0, "y": 0, "size": 100, "dbm": d, "ap": ap} for d, ap in ((-50, KITCHEN), (-60, KITCHEN), (-70, GARAGE))]
    cells += [{"x": 500, "y": 0, "size": 100, "dbm": -80, "ap": GARAGE}, {"x": 900, "y": 0, "size": 100, "dbm": -40, "ap": GARAGE}]
    room_of = lambda x, y: "Kitchen" if x < 400 else "Garage" if x < 800 else None   # noqa: E731
    out = heat.rooms(cells, room_of)
    assert [r["room"] for r in out] == ["Garage", "Kitchen"]
    assert out[1] == {"room": "Kitchen", "dbm": -60, "worst": -70, "cells": 3, "ap": KITCHEN}


def test_clean_keeps_only_well_formed_parts():
    s = heat.new_store()
    heat.add(s, "Ground", 10, 10, SCALE, KITCHEN, -50, "p", 5, reference=True)
    data = {"cells": {**s["cells"], "bad": {"aps": {}}, "G|1|1": {"t": "x", "aps": {KITCHEN: [1, "a", 0, 0]}},
                      "G|2|2": {"t": 1, "aps": {KITCHEN: [0, 0, 2, -100]}}, "G|3|3": "junk"},
            "bias": {"watch": -40.0, "phone": float("inf"), 3: 1}}
    out = heat.clean(data)
    assert list(out["cells"]) == ["Ground|0|0"] and out["bias"] == {"watch": -heat.BIAS_MAX_DB} and out["last"] == {}
    assert heat.clean(None) == heat.new_store() and heat.clean({"cells": [], "bias": "x"}) == heat.new_store()


def test_a_proxys_wifi_mac_is_its_bluetooth_address_minus_two():
    clients = {"d0:cf:13:e1:73:78", "3c:dc:75:8e:31:a6"}
    assert heat.wifi_mac_for_proxy("D0:CF:13:E1:73:7A", clients) == "d0:cf:13:e1:73:78"
    assert heat.wifi_mac_for_proxy("3c:dc:75:8e:31:a6", clients) == "3c:dc:75:8e:31:a6"   # reports its Wi-Fi MAC
    assert heat.wifi_mac_for_proxy("aa:bb:cc:dd:ee:ff", clients) is None                  # Ethernet, or not on Wi-Fi
    assert heat.wifi_mac_for_proxy("00:00:00:00:00:01", {"00:00:00:00:00:01"}) == "00:00:00:00:00:01"
    assert heat.wifi_mac_for_proxy(None, clients) is None and heat.wifi_mac_for_proxy("zz", clients) is None


# --- the collector (__init__) ----------------------------------------------------

def _hass(clients):
    raw = [types.SimpleNamespace(raw=c) for c in clients]
    hub = types.SimpleNamespace(api=types.SimpleNamespace(clients={i: r for i, r in enumerate(raw)}, devices={}))
    entry = types.SimpleNamespace(runtime_data=hub)

    class Hass:
        config_entries = types.SimpleNamespace(async_entries=lambda domain: [entry] if domain == "unifi" else [])
    return Hass()


def test_the_collector_samples_placed_proxies_and_each_persons_phone(monkeypatch):
    import sextant as core

    now = 10_000.0
    monkeypatch.setattr(core, "_wifi_heat", heat.new_store())
    monkeypatch.setattr(core, "_wifi_heat_tick", 0.0)
    clients = [
        {"mac": "d0:cf:13:e1:73:78", "ap_mac": KITCHEN, "signal": -48, "last_seen": now - 5},        # the proxy
        {"mac": "3a:26:7a:09:23:91", "ap_mac": KITCHEN, "signal": -61, "last_seen": now - 5},        # David's phone
        {"mac": "02:db:11:5b:db:b4", "ap_mac": KITCHEN, "signal": -70, "last_seen": now - 5},        # his watch: two watches, no sample
        {"mac": "11:22:33:44:55:66", "ap_mac": GARAGE, "signal": -40, "last_seen": now - 5, "is_wired": True},
    ]
    layout = {"floor": [{"name": "Ground", "scale": SCALE, "receivers": [
        {"entity_id": "kitchen_proxy", "address": "d0:cf:13:e1:73:7a", "cords": {"x": 120, "y": 130}},
        {"entity_id": "eth_proxy", "address": "aa:bb:cc:dd:ee:ff", "cords": {"x": 500, "y": 500}}]}]}
    view = {"assigned": {"person.david": [{"entity": "device_tracker.iphone"}, {"entity": "device_tracker.watch"}]},
            "candidates": {"device_tracker.iphone": {"name": "David's Phone", "home": True, "mac": "3a:26:7a:09:23:91"},
                           "device_tracker.watch": {"name": "Watch", "home": True, "mac": "02:db:11:5b:db:b4"}}}
    by_person = {"person.david": ["david_phone", "watch_a", "watch_b"]}
    classes = {"david_phone": "phone", "watch_a": "watch", "watch_b": "watch"}
    rows = {"david_phone": {"floor": "Ground", "cords": [350, 360], "updated": now - 2},
            "watch_a": {"floor": "Ground", "cords": [10, 10], "updated": now - 2},
            "watch_b": {"floor": "Ground", "cords": [20, 20], "updated": now - 2}}
    core._wifi_heat_cycle(_hass(clients), layout, view, by_person, rows, classes, now)
    cells = core._wifi_heat["cells"]
    assert cells["Ground|1|1"]["aps"][KITCHEN] == [1.0, -48.0, 1.0, -48.0]   # the proxy: a reference sample
    assert cells["Ground|3|3"]["aps"][KITCHEN] == [1.0, -61.0, 0.0, 0.0]     # the phone where its fix is
    assert len(cells) == 2
    # Sampled at most every WIFI_HEAT_EVERY_S, and each client every SAMPLE_EVERY_S.
    core._wifi_heat_cycle(_hass(clients), layout, view, by_person, rows, classes, now + 1)
    core._wifi_heat_cycle(_hass(clients), layout, view, by_person, rows, classes, now + 15)
    assert cells["Ground|1|1"]["aps"][KITCHEN][0] == 1.0
    # A stale controller reading, or a stale fix, is not a sample.
    for c in clients:
        c["last_seen"] = now + 40 - 600
    core._wifi_heat_cycle(_hass(clients), layout, view, by_person, rows, classes, now + 40)
    assert cells["Ground|1|1"]["aps"][KITCHEN][0] == 1.0


def test_no_unifi_hub_means_no_samples_and_an_empty_report(monkeypatch):
    import sextant as core

    class Hass:
        config_entries = types.SimpleNamespace(async_entries=lambda domain: [])
    monkeypatch.setattr(core, "_wifi_heat", heat.new_store())
    monkeypatch.setattr(core, "_wifi_heat_tick", 0.0)
    assert core._unifi_clients(Hass()) is None
    core._wifi_heat_cycle(Hass(), {"floor": []}, {}, {}, {}, {}, 1000.0)
    assert core._wifi_heat["cells"] == {}
    report = core.wifi_heat_report(Hass(), {"floor": [{"name": "Ground", "scale": SCALE}]}, "Ground")
    assert report["cells"] == [] and report["rooms"] == [] and report["samples"] == 0


def test_the_report_gives_the_floors_cells_and_ranks_rooms(monkeypatch):
    import sextant as core

    s = heat.new_store()
    for _ in range(3):
        heat.add(s, "Ground", 50, 50, SCALE, KITCHEN, -55, "p", 0, reference=True)
        heat.add(s, "Ground", 450, 50, SCALE, GARAGE, -78, "q", 0, reference=True)
    monkeypatch.setattr(core, "_wifi_heat", s)
    square = lambda x0: [{"x": x0, "y": 0}, {"x": x0 + 300, "y": 0}, {"x": x0 + 300, "y": 300}, {"x": x0, "y": 300}]   # noqa: E731
    layout = {"floor": [{"name": "Ground", "scale": SCALE, "zones": [
        {"entity_id": "Kitchen", "cords": square(0), "poly": True}, {"entity_id": "Garage", "cords": square(400), "poly": True}]}]}

    class Hass:
        config_entries = types.SimpleNamespace(async_entries=lambda domain: [])
    report = core.wifi_heat_report(Hass(), layout, "Ground")
    assert len(report["cells"]) == 2 and report["samples"] == 6
    assert [(r["floor"], r["room"], r["dbm"]) for r in report["rooms"]] == [("Ground", "Garage", -78.0), ("Ground", "Kitchen", -55.0)]
    assert core.wifi_heat_report(Hass(), layout)["cells"] == []


def test_offsets_are_named_by_whose_device_it_is(monkeypatch):
    import sextant as core

    s = heat.new_store()
    s["bias"] = {"02:db:11:5b:db:b4": -4.4, "aa:aa:aa:aa:aa:aa": 1.0}
    monkeypatch.setattr(core, "_wifi_heat", s)
    monkeypatch.setattr(core, "_wifi_now", {"candidates": {"device_tracker.watch_2": {"name": "Watch", "mac": "02:db:11:5b:db:b4"}},
                                            "assigned": {"person.michelle_bauer": [{"entity": "device_tracker.watch_2"}]}})

    class Hass:
        config_entries = types.SimpleNamespace(async_entries=lambda domain: [])
        states = types.SimpleNamespace(get=lambda e: types.SimpleNamespace(attributes={"friendly_name": "Michelle Bauer"}) if e == "person.michelle_bauer" else None)
    assert core.wifi_heat_report(Hass(), {"floor": []})["bias"] == {"Michelle's Watch": -4.4}
