"""A device Bermuda renamed takes its settings to the new slug.

Bermuda names a device after whatever it can resolve - its beacon id, or a
name the beacon advertises - and which wins can change across a restart: the
same beacon tracked under three slugs in a week, every rename stranding its
name, class, colour and owner on the old one. carry_renamed_thing_settings
matches slugs by Bermuda's stable unique_id (remembered in the layout's
thing_ids) and moves the settings across, so a rename costs one cycle
instead of a re-setup - and the orphan sweep, which would otherwise delete
the old name's settings after its grace, finds nothing left to take.
"""
import asyncio

import sextant
from sextant import storage as st
from conftest import make_hass


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _hass(tmp_path):
    hass = make_hass(tmp_path)
    layout = {
        "floor": [{"name": "F", "scale": 100.0, "receivers": [], "zones": [], "subzones": []}],
        "thing_names": {"old_name": "David"},
        "thing_classes": {"old_name": "phone"},
        "thing_owners": {"old_name": "person.david"},
        "thing_locates_owner": {"old_name": True},
        "thing_ids": {"old_name": "irk_1"},
    }
    run(st.save_layout(hass, layout))
    sextant._last_seen["old_name"] = {"zone": "Office", "updated": 100.0}
    return hass


def test_a_rename_carries_the_settings_to_the_new_slug(tmp_path):
    hass = _hass(tmp_path)
    # Bermuda now tracks the same device (irk_1) under a new name, bare.
    run(sextant.carry_renamed_thing_settings(hass, {"new_name"}, {"new_name": "irk_1"}))
    lay = st.get_layout(hass)
    assert lay["thing_names"] == {"new_name": "David"}, "the name followed the device"
    assert lay["thing_owners"] == {"new_name": "person.david"}
    assert lay["thing_classes"] == {"new_name": "phone"}
    assert lay["thing_locates_owner"] == {"new_name": True}
    assert lay["thing_ids"]["new_name"] == "irk_1", "the identity is remembered"
    assert lay["thing_ids"]["old_name"] == "irk_1", "and the old name's identity kept for a rename back"
    assert "old_name" not in sextant._last_seen and sextant._last_seen["new_name"]["zone"] == "Office"
    # The old slug is swept away as the same device, not left as a ghost:
    # nothing of it remains outside thing_ids.
    assert not any("old_name" in t for k, t in lay.items() if k.startswith("thing_") and k != "thing_ids")


def test_a_thing_with_its_own_settings_is_not_overwritten(tmp_path):
    hass = _hass(tmp_path)
    run(st.save_layout(hass, {**st.get_layout(hass), "thing_names": {"old_name": "David", "new_name": "New Thing"}}))
    run(sextant.carry_renamed_thing_settings(hass, {"new_name"}, {"new_name": "irk_1"}))
    lay = st.get_layout(hass)
    assert lay["thing_names"]["new_name"] == "New Thing", "what the user set by hand stands"
    assert lay["thing_owners"] == {"old_name": "person.david"}, "the old name keeps everything"


def test_a_slug_with_no_identity_is_left_alone(tmp_path):
    # Robots and anything Bermuda does not name by unique_id have no entry in
    # ids: there is nothing to match by, so nothing happens.
    hass = _hass(tmp_path)
    run(st.save_layout(hass, {**st.get_layout(hass), "thing_names": {"old_name": "David", "vacuum_rocky": "Rocky"}}))
    run(sextant.carry_renamed_thing_settings(hass, {"vacuum_rocky"}, {}))
    lay = st.get_layout(hass)
    assert lay["thing_names"]["old_name"] == "David"


def test_ids_are_remembered_without_touching_settings(tmp_path):
    # A first sighting of a slug records its identity even when no rename is
    # involved - that is what a future rename will match by - and the second
    # cycle with nothing new writes nothing.
    hass = _hass(tmp_path)
    saves_before = len(hass._store_saves)
    run(sextant.carry_renamed_thing_settings(hass, {"old_name", "phone"}, {"old_name": "irk_1", "phone": "irk_2"}))
    lay = st.get_layout(hass)
    assert lay["thing_ids"]["phone"] == "irk_2"
    saves = len(hass._store_saves)
    run(sextant.carry_renamed_thing_settings(hass, {"old_name", "phone"}, {"old_name": "irk_1", "phone": "irk_2"}))
    assert len(hass._store_saves) == saves, "an unchanged identity writes nothing"
    assert saves > saves_before


def test_the_sweep_never_takes_the_identity_memory(tmp_path, monkeypatch):
    # thing_ids outlives the things it names: a dead slug's entry is what a
    # future rename matches by, so neither the sweep nor the Forget button
    # deletes it.
    from sextant import bermuda_source
    hass = _hass(tmp_path)
    monkeypatch.setattr(bermuda_source, "async_get_findmy_accessories", lambda h: [])
    monkeypatch.setattr(bermuda_source, "async_get_tracked_devices", lambda h: {})
    hass.data.setdefault(sextant.DOMAIN, {})["orphan_since"] = {
        "old_name": sextant.time.time() - sextant.ORPHAN_GRACE_S * 2}
    run(sextant.sweep_untracked_things(hass, {"phone"}))
    lay = st.get_layout(hass)
    assert lay["thing_ids"].get("old_name") == "irk_1", "the identity memory survives the sweep"
    assert "old_name" not in lay["thing_names"], "the settings still go"
