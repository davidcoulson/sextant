"""The orphan sweep: a slug Bermuda no longer tracks stops haunting the list.

A device whose slug changed (a rename, an IRK swap, a Tile whose ID rotated)
lived on as an "away" row on the Live page for ever, held only by its entries
in the layout's thing_* maps - which the Live page lists - while the Things
page shows only what Bermuda tracks now, so nothing in the UI could even see
it. The sensors of such an orphan were already reconciled away
(prune_sensors_for_untracked); sweep_untracked_things finishes the job the
Forget button does by hand, once the orphan has been one for an hour.
"""
import asyncio
import time

import sextant
from sextant import bermuda_source
from sextant import storage as st
from conftest import make_hass


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _hass(tmp_path, monkeypatch):
    hass = make_hass(tmp_path)
    layout = {
        "floor": [{"name": "F", "scale": 100.0, "receivers": [], "zones": [], "subzones": []}],
        "robots": {"vacuum.rocky": {"floor": "F", "fit": {"transform": [[1, 0], [0, 1]]}}},
        "thing_names": {"old_irk": "David", "phone": "David"},
        "thing_classes": {"old_irk": "phone", "phone": "phone"},
        "thing_owners": {"old_irk": "person.david", "phone": "person.david"},
    }
    run(st.save_layout(hass, layout))

    async def _noop(h):
        return None
    monkeypatch.setattr(sextant, "_save_runtime", _noop)
    # Bermuda answers, and has no FindMy accessory waiting to be heard.
    monkeypatch.setattr(bermuda_source, "async_get_findmy_accessories", lambda h: [])
    monkeypatch.setattr(bermuda_source, "async_get_tracked_devices", lambda h: {})
    for table, ents in ((sextant._last_seen, ("old_irk", "phone", "vacuum_rocky")),
                        (sextant._zone_state, ("old_irk",))):
        for ent in ents:
            table[ent] = {"zone": "Office", "updated": 1.0}
    return hass


def _stamp(hass, ent, age_s):
    hass.data.setdefault(sextant.DOMAIN, {})["orphan_since"] = {ent: time.time() - age_s}


def test_an_orphan_within_its_grace_keeps_everything(tmp_path, monkeypatch):
    hass = _hass(tmp_path, monkeypatch)
    assert run(sextant.sweep_untracked_things(hass, {"phone"})) == []
    lay = st.get_layout(hass)
    assert lay["thing_names"]["old_irk"] == "David"
    assert lay["thing_owners"]["old_irk"] == "person.david"
    assert "old_irk" in sextant._last_seen, "the sweep waits, it does not act"
    # The wait started: the stamp is this cycle's.
    since = hass.data[sextant.DOMAIN]["orphan_since"]
    assert time.time() - since["old_irk"] < sextant.ORPHAN_GRACE_S


def test_an_orphan_past_its_grace_is_forgotten(tmp_path, monkeypatch):
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "old_irk", sextant.ORPHAN_GRACE_S + 5)
    assert run(sextant.sweep_untracked_things(hass, {"phone"})) == ["old_irk"]
    lay = st.get_layout(hass)
    assert "old_irk" not in lay["thing_names"] and "old_irk" not in lay["thing_classes"]
    assert "old_irk" not in lay["thing_owners"], "a ghost pinned to its owner goes from owners too"
    assert lay["thing_names"]["phone"] == "David", "the live slug keeps its settings"
    assert "old_irk" not in sextant._last_seen and "old_irk" not in sextant._zone_state
    assert "old_irk" not in hass.data[sextant.DOMAIN]["orphan_since"]


def test_an_empty_tracked_set_sweeps_nothing(tmp_path, monkeypatch):
    # A Bermuda reload reports nothing for a moment; that must not read as
    # "everything is an orphan".
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "old_irk", sextant.ORPHAN_GRACE_S * 10)
    assert run(sextant.sweep_untracked_things(hass, set())) == []
    assert "old_irk" in st.get_layout(hass)["thing_names"]


def test_a_slug_back_in_the_tracked_set_gets_a_fresh_grace(tmp_path, monkeypatch):
    # Bermuda's answer wobbles (a reload, a rename undone): an orphan that
    # comes back is no orphan, and if it leaves again the hour starts again.
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "old_irk", sextant.ORPHAN_GRACE_S * 10)
    assert run(sextant.sweep_untracked_things(hass, {"old_irk", "phone"})) == []
    assert "old_irk" not in hass.data[sextant.DOMAIN]["orphan_since"]
    _stamp(hass, "phone", sextant.ORPHAN_GRACE_S + 5)   # no longer tracked, and stale-stamped
    assert run(sextant.sweep_untracked_things(hass, {"old_irk"})) == ["phone"]


def test_a_robot_thing_is_never_an_orphan(tmp_path, monkeypatch):
    # The caller unions Bermuda's set with robot_things(); a vacuum lined up
    # with a floor is Sextant's own thing and Bermuda will never name it.
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "vacuum_rocky", sextant.ORPHAN_GRACE_S * 10)
    assert run(sextant.sweep_untracked_things(hass, {"phone", "vacuum_rocky"})) == []
    assert "vacuum_rocky" in sextant._last_seen


def test_a_tracked_thing_away_from_home_is_never_swept(tmp_path, monkeypatch):
    # "Tracked" is Bermuda's configuration, not its ears: a phone away from
    # home for a month is still in the tracked set, so the sweep - like the
    # sensors reconcile before it, whose docstring says exactly this - never
    # touches it. Away is stale_after/away_after business, not the sweep's.
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "phone", sextant.ORPHAN_GRACE_S * 1000)   # a stamp old beyond any grace
    sextant._last_seen["phone"] = {"zone": "Office", "updated": time.time() - 30 * 86400}
    assert run(sextant.sweep_untracked_things(hass, {"phone"})) == []
    lay = st.get_layout(hass)
    assert lay["thing_names"]["phone"] == "David"
    assert lay["thing_owners"]["phone"] == "person.david"
    assert "phone" in sextant._last_seen, "even its month-old sighting stays"


def test_nothing_is_swept_while_a_findmy_accessory_is_unheard(tmp_path, monkeypatch):
    # Bermuda tracks a FindMy accessory only once it has heard it: after a
    # restart an AirTag that is away is configured but outside the tracked
    # set, exactly like a ghost. Until every accessory is in, hold.
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "old_irk", sextant.ORPHAN_GRACE_S + 5)
    monkeypatch.setattr(bermuda_source, "async_get_findmy_accessories", lambda h: [{"address": "findmy_AB"}])
    assert run(sextant.sweep_untracked_things(hass, {"phone"})) == []
    monkeypatch.setattr(bermuda_source, "async_get_findmy_accessories", lambda h: None)   # cannot say
    assert run(sextant.sweep_untracked_things(hass, {"phone"})) == []
    assert "old_irk" in st.get_layout(hass)["thing_names"]
    monkeypatch.setattr(bermuda_source, "async_get_findmy_accessories", lambda h: [{"address": "findmy_AB"}])
    monkeypatch.setattr(bermuda_source, "async_get_tracked_devices", lambda h: {"findmy_ab": {"slug": "keys"}})
    assert run(sextant.sweep_untracked_things(hass, {"phone", "keys"})) == ["old_irk"]


def test_a_robot_not_lined_up_yet_keeps_its_settings(tmp_path, monkeypatch):
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "vacuum_rocky", sextant.ORPHAN_GRACE_S * 10)
    assert run(sextant.sweep_untracked_things(hass, {"phone"})) == []
    assert "vacuum_rocky" in sextant._last_seen


def test_the_learned_range_scale_goes_with_the_ghost(tmp_path, monkeypatch):
    hass = _hass(tmp_path, monkeypatch)
    monkeypatch.setitem(sextant._range_scale, "old_irk", 0.8)
    saved = []

    async def _save(h, snap):
        saved.append(snap)
    monkeypatch.setattr(sextant, "save_fp_gains", _save)
    _stamp(hass, "old_irk", sextant.ORPHAN_GRACE_S + 5)
    assert run(sextant.sweep_untracked_things(hass, {"phone"})) == ["old_irk"]
    assert "old_irk" not in sextant._range_scale
    assert saved and "old_irk" not in saved[-1]["range_scale"]


def test_a_thing_back_during_a_hold_still_gets_a_fresh_grace(tmp_path, monkeypatch):
    hass = _hass(tmp_path, monkeypatch)
    _stamp(hass, "old_irk", sextant.ORPHAN_GRACE_S * 10)
    monkeypatch.setattr(bermuda_source, "async_get_findmy_accessories", lambda h: [{"address": "findmy_AB"}])
    assert run(sextant.sweep_untracked_things(hass, {"old_irk", "phone"})) == []
    assert "old_irk" not in hass.data[sextant.DOMAIN]["orphan_since"]
