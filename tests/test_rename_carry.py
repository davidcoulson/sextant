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


def test_pins_follow_the_rename(tmp_path):
    hass = _hass(tmp_path)
    run(st.save_truth(hass, {"marks": [{"id": 1, "entity": "old_name", "floor": "F", "x": 1.0, "y": 2.0},
                                       {"id": 2, "entity": "phone", "floor": "F", "x": 3.0, "y": 4.0}], "next_id": 3}))
    run(sextant.carry_renamed_thing_settings(hass, {"new_name"}, {"new_name": "irk_1"}))
    marks = run(st.load_truth(hass))["marks"]
    assert [m["entity"] for m in marks] == ["new_name", "phone"]


def test_a_slug_another_device_took_hands_its_settings_to_their_device(tmp_path):
    # old_name (irk_1) became new_name, and another device (irk_9) took old_name.
    hass = _hass(tmp_path)
    run(sextant.carry_renamed_thing_settings(hass, {"new_name", "old_name"}, {"new_name": "irk_1", "old_name": "irk_9"}))
    lay = st.get_layout(hass)
    assert lay["thing_names"] == {"new_name": "David"} and lay["thing_owners"] == {"new_name": "person.david"}
    assert lay["thing_ids"]["old_name"] == "irk_9"
    assert "old_name" in sextant._last_seen, "the device now on old_name keeps its own sighting"


def test_two_slugs_claiming_one_device_carry_nothing(tmp_path):
    hass = _hass(tmp_path)
    run(sextant.carry_renamed_thing_settings(hass, {"a", "b"}, {"a": "irk_1", "b": "irk_1"}))
    assert st.get_layout(hass)["thing_names"] == {"old_name": "David"}


def test_two_devices_under_one_slug_have_no_identity(monkeypatch):
    from sextant import bermuda_source
    monkeypatch.setattr(bermuda_source, "async_get_tracked_devices", lambda h: {
        "aa": {"slug": "tag", "unique_id": "u1"}, "bb": {"slug": "tag", "unique_id": "u2"}, "cc": {"slug": "p", "unique_id": "u3"},
        "dd": {"slug": "q", "unique_id": "u4"}, "ee": {"slug": "q"}})
    assert bermuda_source.async_get_tracked_unique_ids(None) == {"p": "u3", "tag": None, "q": None}


def test_a_newcomer_on_the_old_slug_before_the_rename_shows_takes_nothing(tmp_path):
    # Cycle 1: another device (irk_9) takes old_name; the device itself (irk_1) is not heard yet.
    hass = _hass(tmp_path)
    run(sextant.carry_renamed_thing_settings(hass, {"old_name"}, {"old_name": "irk_9"}))
    assert st.get_layout(hass)["thing_ids"]["old_name"] == "irk_1", "the memory waits for the settings to move"
    # Cycle 2: irk_1 shows up as new_name and gets its settings; old_name is irk_9's from now on.
    run(sextant.carry_renamed_thing_settings(hass, {"old_name", "new_name"}, {"old_name": "irk_9", "new_name": "irk_1"}))
    lay = st.get_layout(hass)
    assert lay["thing_names"] == {"new_name": "David"} and lay["thing_ids"]["old_name"] == "irk_9"


def test_a_slug_two_devices_share_is_never_a_donor(tmp_path):
    # old_name (irk_1) is now shared by two devices, so Bermuda's ids leave it out.
    hass = _hass(tmp_path)
    run(sextant.carry_renamed_thing_settings(hass, {"new_name"}, {"new_name": "irk_1", "old_name": None}))
    assert st.get_layout(hass)["thing_names"] == {"old_name": "David"}


def test_a_damaged_identity_memory_is_ignored(tmp_path):
    hass = _hass(tmp_path)
    run(st.save_layout(hass, {**st.get_layout(hass), "thing_ids": {"old_name": [], "x": "irk_3"}}))
    run(sextant.carry_renamed_thing_settings(hass, {"new_name"}, {"new_name": "irk_1"}))


def test_a_name_set_while_waiting_keeps_the_old_slug_s_identity(tmp_path, monkeypatch):
    # The move to new_name is cancelled because new_name got settings meanwhile:
    # old_name must not be relabelled as the newcomer's, or it would later take them.
    hass = _hass(tmp_path)
    real = sextant.get_layout_for_edit
    def edited(h):
        lay = real(h)
        lay.setdefault("thing_names", {})["new_name"] = "Manual"
        return lay
    monkeypatch.setattr(sextant, "get_layout_for_edit", edited)
    run(sextant.carry_renamed_thing_settings(hass, {"old_name", "new_name"}, {"old_name": "irk_9", "new_name": "irk_1"}))
    lay = st.get_layout(hass)
    assert lay["thing_ids"]["old_name"] == "irk_1" and lay["thing_names"]["old_name"] == "David"


def test_settings_gone_while_waiting_move_nothing(tmp_path, monkeypatch):
    # A restore took old_name's settings while the carry waited for the lock:
    # nothing is left to hand over, so its pins stay put, and the bare slug is
    # the device's that Bermuda reports on it now (as any bare slug's is).
    hass = _hass(tmp_path)
    run(st.save_truth(hass, {"marks": [{"id": 1, "entity": "old_name", "floor": "F", "x": 1.0, "y": 2.0}], "next_id": 2}))
    real = sextant.get_layout_for_edit
    def restored(h):
        lay = real(h)
        for table in sextant._thing_settings_tables(lay).values():
            table.pop("old_name", None)
        return lay
    monkeypatch.setattr(sextant, "get_layout_for_edit", restored)
    run(sextant.carry_renamed_thing_settings(hass, {"old_name", "new_name"}, {"old_name": "irk_9", "new_name": "irk_1"}))
    lay = st.get_layout(hass)
    assert lay["thing_ids"]["old_name"] == "irk_9" and "new_name" not in lay.get("thing_names", {})
    assert [m["entity"] for m in run(st.load_truth(hass))["marks"]] == ["old_name"]


def test_a_restore_that_gave_the_old_slug_to_another_device_moves_nothing(tmp_path, monkeypatch):
    # A restore landed while the carry waited for the lock: old_name still has
    # settings, but the restored memory says they are another device's (irk_7).
    # The plan is made from the layout read under the lock, so they stay put.
    hass = _hass(tmp_path)
    run(st.save_truth(hass, {"marks": [{"id": 1, "entity": "old_name", "floor": "F", "x": 1.0, "y": 2.0}], "next_id": 2}))
    real = sextant.get_layout_for_edit
    def restored(h):
        lay = real(h)
        lay["thing_names"] = {"old_name": "Other"}
        lay["thing_ids"] = {"old_name": "irk_7"}
        return lay
    monkeypatch.setattr(sextant, "get_layout_for_edit", restored)
    run(sextant.carry_renamed_thing_settings(hass, {"new_name"}, {"new_name": "irk_1"}))
    lay = st.get_layout(hass)
    assert lay["thing_names"] == {"old_name": "Other"}, "the other device keeps its name"
    assert lay["thing_ids"] == {"old_name": "irk_7", "new_name": "irk_1"}
    assert "old_name" in sextant._last_seen, "and its sighting"
    assert [m["entity"] for m in run(st.load_truth(hass))["marks"]] == ["old_name"]


def test_a_slug_bermuda_reports_now_is_tracked_for_the_sensor_prune(tmp_path, monkeypatch):
    # The cached prefix set has not caught up with new_name, which Bermuda
    # already reports: the prune must not take its sensors for an orphan's.
    from sextant import bermuda_source, sensor
    hass = _hass(tmp_path)
    pruned_with = []
    def prune(h, tracked):
        pruned_with.append(set(tracked))
        raise asyncio.CancelledError   # one look is enough: this ends the loop
    async def nothing(*args, **kwargs):
        return None
    for name in ("update_receiver_liveness", "flush_position_history", "prune_stale_positions"):
        monkeypatch.setattr(sextant, name, nothing)
    monkeypatch.setattr(bermuda_source, "async_get_tracked_device_prefixes", lambda h: {"old_name"})
    monkeypatch.setattr(bermuda_source, "async_get_tracked_unique_ids", lambda h: {"new_name": "irk_1"})
    monkeypatch.setattr(sensor, "prune_sensors_for_untracked", prune)
    try:
        run(sextant.update_tracked_entities(hass))
    except asyncio.CancelledError:
        pass
    assert pruned_with == [{"old_name", "new_name"}]
