"""Receivers identified by scanner address: resolution, relabel on rename,
address-keyed readings, liveness and calibration matching."""

import asyncio
import copy

import sextant
from sextant import bermuda_source
from sextant import calibration as cal_mod
from sextant import storage as st
from conftest import make_hass


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


DIRECTORY = {
    "aa:bb:cc:01:02:0a": {"slug": "robin_bedroom_rrn00_010208", "name": "Robin Bedroom RRN00 010208",
                          "unique_id": "aa:bb:cc:01:02:08", "address_wifi_mac": "aa:bb:cc:01:02:08", "last_seen_age": 2.0},
    "aa:bb:cc:03:04:0a": {"slug": "robin_bedroom_rrn00_030408", "name": "Robin Bedroom RRN00 030408",
                          "unique_id": "aa:bb:cc:03:04:08", "address_wifi_mac": "aa:bb:cc:03:04:08", "last_seen_age": 400.0},
    "aa:bb:cc:05:06:0a": {"slug": "foyer_s2224_050608_renamed", "name": "Foyer s2224 050608 renamed",
                          "unique_id": "aa:bb:cc:05:06:08", "address_wifi_mac": "aa:bb:cc:05:06:08", "last_seen_age": 1.0},
}


def _layout():
    return {"floor": [{"name": "F", "scale": 100.0, "zones": [], "subzones": [], "receivers": [
        {"entity_id": "robin_bedroom_rrn00_010208", "cords": {"x": 0, "y": 0}},           # exact slug
        {"entity_id": "robin_bedroom_rrn00_030408", "cords": {"x": 1, "y": 0}, "address": "AA:BB:CC:03:04:0A"},  # stored, upper-case
        {"entity_id": "foyer_s2224_050608", "cords": {"x": 2, "y": 0}},                   # renamed in Bermuda: token match
        {"entity_id": "ghost_rrn00_000000", "cords": {"x": 3, "y": 0}},                   # gone
    ]}]}


def test_resolver_assigns_addresses_and_relabels_renamed_receivers():
    layout = _layout()
    changed, unresolved = sextant._resolve_receiver_addresses(layout, DIRECTORY)
    recs = {r["cords"]["x"]: r for r in layout["floor"][0]["receivers"]}
    assert changed is True
    assert recs[0]["address"] == "aa:bb:cc:01:02:0a"
    assert recs[1]["address"] == "aa:bb:cc:03:04:0a"                     # normalised
    assert recs[2]["address"] == "aa:bb:cc:05:06:0a"
    assert recs[2]["entity_id"] == "foyer_s2224_050608_renamed"           # label follows the rename
    assert "address" not in recs[3] and unresolved == ["ghost_rrn00_000000"]
    # Idempotent: a second pass changes nothing.
    assert sextant._resolve_receiver_addresses(layout, DIRECTORY) == (False, ["ghost_rrn00_000000"])


def test_resolver_never_assigns_one_scanner_to_two_placements():
    layout = {"floor": [{"name": "F", "scale": 100.0, "receivers": [
        {"entity_id": "robin_bedroom_rrn00_010208", "cords": {"x": 0, "y": 0}},
        {"entity_id": "old_name_rrn00_010208", "cords": {"x": 1, "y": 0}},   # same token, duplicate placement
    ]}]}
    sextant._resolve_receiver_addresses(layout, DIRECTORY)
    addrs = [r.get("address") for r in layout["floor"][0]["receivers"]]
    assert addrs == ["aa:bb:cc:01:02:0a", None]


def test_async_resolver_persists_only_when_something_changed(monkeypatch, tmp_path):
    hass = make_hass(tmp_path)
    run(st.save_layout(hass, _layout()))
    monkeypatch.setattr(bermuda_source, "async_get_scanner_directory", lambda h: DIRECTORY)
    saves_before = len(hass._store_saves)
    assert run(sextant.async_resolve_receiver_addresses(hass)) is True
    assert len(hass._store_saves) == saves_before + 1
    assert st.get_layout(hass)["floor"][0]["receivers"][0]["address"] == "aa:bb:cc:01:02:0a"
    assert run(sextant.async_resolve_receiver_addresses(hass)) is False
    assert len(hass._store_saves) == saves_before + 1
    monkeypatch.setattr(bermuda_source, "async_get_scanner_directory", lambda h: None)
    assert run(sextant.async_resolve_receiver_addresses(hass)) is False


def test_readings_by_address_need_no_slug_map(monkeypatch):
    from test_bermuda_source import _install_featureful_api, _snapshot, _hass_with_data
    api = _install_featureful_api(monkeypatch, _snapshot(distance=2.3, age=1.0))
    readings = bermuda_source.async_get_readings_by_address(_hass_with_data())
    assert readings[("phone", "11:22:33:44:55:66")] == {"distance": 2.3, "age": 1.0}
    assert api.calls[-1] == {"tracked_only": True}


def test_radii_use_the_address_when_the_slug_has_drifted(monkeypatch):
    import types
    hass = make_hass()
    hass.states = types.SimpleNamespace(get=lambda eid: None)  # entity fallback finds nothing
    monkeypatch.setattr(bermuda_source, "async_get_readings", lambda h, include_history=False: {})
    monkeypatch.setattr(bermuda_source, "async_get_readings_by_address",
                        lambda h, include_history=False: {("e", "aa:bb:cc:01:02:0a"): {"distance": 3.0, "age": 1.0}})
    data = {"floor": [{"name": "F", "scale": 100.0, "receivers": [
        {"entity_id": "stale_label", "address": "AA:BB:CC:01:02:0A", "cords": {"x": 0, "y": 0}},
        {"entity_id": "unresolved", "cords": {"x": 1, "y": 0}},
    ]}]}
    run(sextant.update_receiver_radii(hass, {"entity": "e", "data": data}))
    r0, r1 = data["floor"][0]["receivers"]
    assert r0["distance"] == 3.0 and r0["cords"]["r"] == 300.0
    assert "distance" not in r1


def test_diagnostics_do_not_flag_a_placement_identified_by_address(monkeypatch):
    import json
    hass = make_hass()
    monkeypatch.setattr(bermuda_source, "async_get_scanner_directory", lambda h: DIRECTORY)
    monkeypatch.setattr(sextant, "_scanner_slugs_and_readings", lambda h: ({"robin_bedroom_rrn00_030408"}, set()))
    layout = {"floor": [{"name": "F", "receivers": [
        {"entity_id": "old_label", "address": "aa:bb:cc:01:02:0a"},   # linked by address, label stale
        {"entity_id": "ghost_rrn00_000000"},                            # genuinely unmatched
    ]}]}
    diag = sextant._scanner_diagnostics(hass, json.dumps(layout))
    assert [u["entity_id"] for u in diag["unmatched_receivers"]] == ["ghost_rrn00_000000"]


def test_calibration_matches_scanners_by_address_first():
    cal = {"receivers": {
        "kitchen_label": {"address": "aa:aa:aa:aa:aa:01", "floor": "F", "x": 0, "y": 0, "scale": 100.0},
        "office_rrn00_aaaa02": {"address": None, "floor": "F", "x": 1, "y": 0, "scale": 100.0},
    }, "all_placed_slugs": {"kitchen_label", "office_rrn00_aaaa02"}}
    devices = {
        "aa:aa:aa:aa:aa:01": {"_is_scanner": True, "address": "aa:aa:aa:aa:aa:01", "name": "Kitchen Renamed Probe"},
        "aa:aa:aa:aa:aa:02": {"_is_scanner": True, "address": "aa:aa:aa:aa:aa:02", "name": "Office RRN00 aaaa02"},
    }
    mapping = cal_mod._match_scanners(cal, devices)
    assert mapping == {"aa:aa:aa:aa:aa:01": "kitchen_label", "aa:aa:aa:aa:aa:02": "office_rrn00_aaaa02"}
    assert set(cal["matched_placed"]) == {"kitchen_label", "office_rrn00_aaaa02"}


def test_resolver_handles_bermudas_mac_suffixed_slugs():
    """Bermuda appends the MAC to a duplicate scanner name, and drops it again
    once the duplicate is gone. Both forms must resolve to the address."""
    directory = {"aa:bb:cc:01:02:1e": {"slug": "sewing_room_rrn00_01021c", "name": "Sewing Room RRN00 01021c",
                                        "unique_id": "aa:bb:cc:01:02:1c", "address_wifi_mac": "aa:bb:cc:01:02:1c",
                                        "last_seen_age": 1.0}}
    layout = {"floor": [{"name": "F", "receivers": [
        {"entity_id": "sewing_room_rrn00_01021c_aa_bb_cc_01_02_1e", "cords": {"x": 0, "y": 0}},
    ]}]}
    changed, unresolved = sextant._resolve_receiver_addresses(layout, directory)
    rec = layout["floor"][0]["receivers"][0]
    assert changed and unresolved == []
    assert rec["address"] == "aa:bb:cc:01:02:1e"
    assert rec["entity_id"] == "sewing_room_rrn00_01021c"       # label follows the un-suffixed name
    # And the other way round: the directory has the suffixed name, the
    # placement the plain one.
    directory["aa:bb:cc:01:02:1e"]["slug"] = "sewing_room_rrn00_01021c_aa_bb_cc_01_02_1e"
    layout = {"floor": [{"name": "F", "receivers": [{"entity_id": "sewing_room_rrn00_01021c", "cords": {"x": 0, "y": 0}}]}]}
    assert sextant._resolve_receiver_addresses(layout, directory)[0]
    assert layout["floor"][0]["receivers"][0]["address"] == "aa:bb:cc:01:02:1e"


def test_placed_receivers_takes_a_dict_or_a_json_string():
    import json

    layout = {"floor": [{"name": "G", "receivers": [{"entity_id": "kitchen", "address": "AA:BB", "scanner_uid": "u"}, {"entity_id": ""}, "x"]}]}
    want = [("G", "kitchen", "u", "aa:bb")]
    assert sextant._placed_receivers(layout) == want
    assert sextant._placed_receivers(json.dumps(layout)) == want
    assert sextant._placed_receivers("") == [] and sextant._placed_receivers(None) == [] and sextant._placed_receivers("{bad") == []
