"""Where a thing usually is, by hour (habits.py), and its pull on a close room switch."""
import sextant  # noqa: F401
from datetime import datetime, timezone

from sextant import habits

MON_7AM = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc).timestamp()   # a Monday
SAT_7AM = datetime(2026, 11, 21, 7, 0, tzinfo=timezone.utc).timestamp()


def _spend(store, ent, zone, start, secs):
    t = start
    while t < start + secs:
        habits.learn(store, ent, zone, t + 30, t, timezone.utc)
        t += 30


def test_slots_split_weekday_and_weekend():
    assert habits.slot_of(MON_7AM, timezone.utc) == "wd7" and habits.slot_of(SAT_7AM, timezone.utc) == "we7"


def test_a_routine_tips_a_close_call_only_once_there_is_history():
    s = habits.new_store()
    assert habits.prior_shift(s, "p", "Kitchen", "Foyer", MON_7AM, 0.1, timezone.utc) == 0.0   # no history
    _spend(s, "p", "Kitchen", MON_7AM, 40 * 60)
    _spend(s, "p", "Foyer", MON_7AM + 40 * 60, 10 * 60)
    now = MON_7AM + 50 * 60
    toward_kitchen = habits.prior_shift(s, "p", "Foyer", "Kitchen", now, 0.1, timezone.utc)
    assert toward_kitchen < 0                                      # kitchen is the habit: an easier switch into it
    assert habits.prior_shift(s, "p", "Kitchen", "Foyer", now, 0.1, timezone.utc) > 0
    assert abs(toward_kitchen) <= 0.1
    assert habits.prior_shift(s, "p", "Foyer", "Kitchen", now, 0.0, timezone.utc) == 0.0     # gain 0 = off
    assert habits.prior_shift(s, "p", "Foyer", "Kitchen", SAT_7AM + 3600, 0.1, timezone.utc) == 0.0   # weekend: no history


def test_old_time_fades_and_the_table_stays_bounded_and_clean():
    s = habits.new_store()
    _spend(s, "p", "A", MON_7AM, 30 * 60)
    row = s["p"]["wd7"]
    before = row["z"]["A"]
    habits.learn(s, "p", "B", MON_7AM + 21 * 86400 + 30, MON_7AM + 21 * 86400, timezone.utc)   # same slot, a half-life later
    assert row["z"]["A"] < before * 0.6
    assert habits.clean({"p": {"wd7": {"at": 1, "z": {"A": 5, "B": -1, "C": "x"}}, "bad": 3}, 4: {}}) == {"p": {"wd7": {"at": 1.0, "z": {"A": 5.0}}}}
    assert habits.clean("junk") == {}


def test_stale_history_fades_without_being_added_to_and_clean_caps_rows():
    s = habits.new_store()
    _spend(s, "p", "A", MON_7AM, 30 * 60)
    assert habits.share(s, "p", "A", MON_7AM + 30 * 60, timezone.utc) == 1.0
    assert habits.share(s, "p", "A", MON_7AM + 30 * 60 + 200 * 86400, timezone.utc) is None   # months later: nothing to say
    raw = {"p": {"wd7": {"at": float("inf"), "z": {"A": 5}}, "wd8": {"at": 1, "z": {f"r{i}": i + 1 for i in range(500)}}}}
    out = habits.clean(raw)
    assert "wd7" not in out["p"] and len(out["p"]["wd8"]["z"]) == habits.MAX_ZONES_PER_SLOT


def test_gain_comes_from_the_class_then_the_default_and_pets_have_none():
    layout = {"thing_classes": {"phone1": "phone", "tag1": "dog", "tag2": "cat"}, "class_habit_gain": {"cat": 0.2, "phone": 9, "x": 1}}
    assert habits.gain_for(layout, "phone1", 0.1) == 0.1       # 9 is out of range: ignored
    assert habits.gain_for(layout, "tag1", 0.1) == 0.0          # a dog: no routine by default
    assert habits.gain_for(layout, "tag2", 0.1) == 0.2          # a cat the owner gave a value
    assert habits.gain_for({}, "unknown", 0.1) == 0.1


def test_review_two_fixes_in_habits():
    assert habits.gain_for({"thing_classes": {"p": ["phone"]}, "class_habit_gain": {"phone": 0.2}}, "p", 0.1) == 0.1   # a malformed class is no class
    raw = {"p": {**{f"junk{i}": {"at": 1, "z": {"A": 5}} for i in range(60)}, "wd7": {"at": 1, "z": {"A": 5}}}}
    assert "wd7" in habits.clean(raw)["p"] and len(habits.clean(raw)["p"]) == 1


def test_floor_factors_add_rooms_up_by_floor_and_keep_rare_floors_possible():
    s = habits.new_store()
    assert habits.floor_factors(s, "meg", ["Second", "Ground"], MON_7AM, 0.25, timezone.utc) == {}   # no history
    _spend(s, "meg", "Second|Eilee's Room", MON_7AM, 30 * 60)
    _spend(s, "meg", "Second|Hall", MON_7AM + 30 * 60, 15 * 60)
    _spend(s, "meg", "Ground|Kitchen", MON_7AM + 45 * 60, 5 * 60)
    now = MON_7AM + 50 * 60
    f = habits.floor_factors(s, "meg", ["Second", "Ground", "Basement"], now, 0.5, timezone.utc)
    assert abs(f["Second"] - 0.9 ** 0.5) < 1e-3 and abs(f["Ground"] - 0.1 ** 0.5) < 1e-3
    assert f["Basement"] == habits.FLOOR_FLOOR_SHARE ** 0.5          # never there at this hour: unlikely, not impossible
    assert habits.floor_factors(s, "meg", ["Second"], now, 0.0, timezone.utc) == {}   # weight 0 = off
    assert habits.floor_factors(s, "meg", ["Second"], SAT_7AM, 0.5, timezone.utc) == {}   # weekend: no history


def test_floor_weight_by_class_is_not_off_for_pets():
    layout = {"thing_classes": {"meg": "dog", "p": "phone"}, "class_habit_floor_weight": {"dog": 0.25, "phone": 3}}
    kw = {"table_key": "class_habit_floor_weight", "top": 1.0, "pets_off": False}
    assert habits.gain_for(layout, "meg", 0.0, **kw) == 0.25
    assert habits.gain_for(layout, "p", 0.0, **kw) == 0.0           # 3 is out of range: the default
    assert habits.gain_for({"thing_classes": {"c": "cat"}}, "c", 0.1, **kw) == 0.1


def test_a_pause_covers_its_things_and_classes_until_it_ends():
    layout = {"thing_classes": {"meg": "dog", "ph": "phone"},
              "habit_pauses": [{"until": 100.0, "classes": ["phone"]}, {"until": 50.0, "things": ["meg"]}, "junk", {"until": "x"}]}
    assert habits.paused(layout, "ph", 60) and not habits.paused(layout, "ph", 100)
    assert habits.paused(layout, "meg", 40) and not habits.paused(layout, "meg", 60)
    assert not habits.paused(layout, "other", 40)
    assert habits.paused({"habit_pauses": [{"until": 10.0}]}, "anything", 5)   # naming nothing pauses everything
    assert not habits.paused({}, "meg", 0) and not habits.paused({"habit_pauses": [{"until": 10.0, "things": "meg"}]}, "x", 5)


def test_the_floor_prior_skips_charging_things_unworn_watches_and_pauses(monkeypatch):
    import types
    from sextant import watch_adverts
    core = sextant
    s = habits.new_store()
    now = __import__("time").time()
    for ent in ("ph", "w"):
        s[ent] = {habits.slot_of(now): {"at": now, "z": {"Second|Bed": 3600.0}}}
    monkeypatch.setattr(core, "_habits", s)
    monkeypatch.setattr(core, "_local_tz", None)
    charging = {"sensor.ph_battery_state": "Charging"}
    hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda e: types.SimpleNamespace(state=charging[e]) if e in charging else None))
    layout = {"thing_classes": {"ph": "phone", "w": "watch"}, "tuning": {"habit_floor_weight": 0.5},
              "thing_charging_entity": {"ph": "sensor.ph_battery_state"}}
    assert core._habit_floor_factors(hass, layout, "ph", ["Second", "Ground"]) == {}   # on its charger
    charging["sensor.ph_battery_state"] = "Not Charging"
    assert core._habit_floor_factors(hass, layout, "ph", ["Second", "Ground"])["Second"] > 0.9
    monkeypatch.setattr(watch_adverts, "worn_now", lambda *a: False)
    assert core._habit_floor_factors(hass, layout, "w", ["Second"]) == {}               # off a wrist
    monkeypatch.setattr(watch_adverts, "worn_now", lambda *a: None)
    assert core._habit_floor_factors(hass, layout, "w", ["Second"]) != {}               # unknown: the habit stands
    layout["habit_pauses"] = [{"until": now + 60, "classes": ["watch"]}]
    assert core._habit_floor_factors(hass, layout, "w", ["Second"]) == {}               # paused


def test_a_floor_name_with_a_bar_gets_its_own_share():
    s = habits.new_store()
    _spend(s, "m", "West|Upper|Bed", MON_7AM, 30 * 60)
    f = habits.floor_factors(s, "m", ["West", "West|Upper"], MON_7AM + 30 * 60, 1.0, timezone.utc)
    assert f["West|Upper"] > 0.99 and f["West"] == habits.FLOOR_FLOOR_SHARE


def test_running_pauses_are_the_live_ones_soonest_first():
    layout = {"habit_pauses": [{"until": 90.0}, {"until": 10.0}, {"until": 50.0, "things": ["m"]}, {"until": True}, "x"]}
    assert [p["until"] for p in habits.running_pauses(layout, 20)] == [50.0, 90.0]
    assert habits.running_pauses({}, 0) == [] and habits.running_pauses({"habit_pauses": "x"}, 0) == []
