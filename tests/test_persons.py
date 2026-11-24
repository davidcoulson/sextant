"""A person's location from the things they own (sextant.persons)."""
from datetime import datetime, timezone

import sextant  # noqa: F401
from sextant import persons
from sextant import sensor as sensor_mod

NOW = 10_000.0


def thing(ent, cls, still_for=None, heard_ago=5.0, zone="Great Room", spot=None, floor="Ground Floor"):
    # still_for: how long since it arrived where it is (None: just now).
    return {"ent": ent, "cls": cls, "updated": NOW - heard_ago,
            "arrived": NOW - (still_for or 0),
            "zone": zone, "sub_zone": spot or "unknown", "floor": floor}


def test_owners_groups_things_by_person():
    layout = {"thing_owners": {"watch": "person.alex", "phone": "person.alex", "mphone": "person.sam", "x": "alex"}}
    assert persons.owners(layout) == {"person.alex": ["watch", "phone"], "person.sam": ["mphone"]}
    assert persons.owners({}) == {}


def test_a_person_with_only_gps_owns_nothing_but_is_placed():
    layout = {"thing_owners": {"watch": "person.alex"},
              "person_trackers": {"person.alex": ["device_tracker.d"], "person.sherry": ["device_tracker.s"],
                                  "person.none": []}}
    assert persons.owners(layout) == {"person.alex": ["watch"], "person.sherry": []}
    assert persons.pet_persons(persons.owners(layout), {}) == set()


def test_the_thing_being_carried_speaks_for_its_owner():
    # Phone on the couch for an hour; the watch walked to the kitchen a minute ago.
    phone = thing("phone", "phone", still_for=3600, spot="Couch")
    watch = thing("watch", "watch", still_for=60, zone="Kitchen")
    assert persons.pick([phone, watch], NOW, 120)["ent"] == "watch"


def test_among_things_moved_recently_the_one_usually_worn_wins():
    phone = thing("phone", "phone", still_for=30)
    watch = thing("watch", "watch", still_for=200)
    pods = thing("pods", "headphones", still_for=10)
    assert persons.pick([phone, watch, pods], NOW, 120)["ent"] == "watch"


def test_when_all_still_a_watch_placed_as_well_as_the_phone_wins():
    phone = dict(thing("phone", "phone", still_for=1000), conf=0.6)
    watch = dict(thing("watch", "watch", still_for=1500), conf=0.7)
    assert persons.pick([phone, watch], NOW, 120)["ent"] == "watch"
    weak = dict(watch, conf=0.3)
    assert persons.pick([phone, weak], NOW, 120)["ent"] == "phone"
    assert persons.pick([phone, thing("watch", "watch", still_for=1500)], NOW, 120)["ent"] == "phone"
    zero = [dict(phone, conf=0.0), dict(watch, conf=0.0)]
    assert persons.pick(zero, NOW, 120)["ent"] == "watch"


def test_unheard_or_unplaced_things_do_not_count():
    old = thing("watch", "watch", still_for=10, heard_ago=900)
    lost = thing("phone", "phone", still_for=10, zone="unknown")
    keys = thing("keys", "keys", still_for=4000)
    assert persons.pick([old, lost, keys], NOW, 120)["ent"] == "keys"
    assert persons.pick([old, lost], NOW, 120) is None


def test_states_give_the_spot_or_the_room_and_say_which_thing():
    s = persons.states(thing("phone", "phone", spot="Couch"))
    assert s["sextant_person_location"] == ("Couch", {"kind": "spot", "room": "Great Room", "spot": "Couch", "floor": "Ground Floor",
                                                       "area_id": None, "floor_id": None, "via": "phone", "considered": []})
    linked = persons.states({**thing("phone", "phone", spot="Couch"), "area": ("great_room", "ground")})
    assert linked["sextant_person_location"][1]["area_id"] == "great_room"
    assert linked["sextant_person_location"][1]["floor_id"] == "ground"
    assert linked["sextant_person_room"] == ("Great Room", {"area_id": "great_room", "via": "phone"})
    assert persons.considered([thing("phone", "phone", still_for=600, spot="Couch")], NOW) == [
        {"thing": "phone", "where": "Couch", "here_since": datetime.fromtimestamp(NOW - 600, timezone.utc).replace(microsecond=0).isoformat()}]
    assert s["sextant_person_room"] == ("Great Room", {"area_id": None, "via": "phone"})
    assert persons.states(None)["sextant_person_location"][0] == "unknown"


def test_person_sensors_are_never_mistaken_for_an_untracked_things():
    for suffix, _label in persons.PERSON_SENSOR_KINDS:
        assert sensor_mod.thing_of_unique_id(f"{suffix}_alex_smith") is None


def test_headphones_keys_and_bags_do_not_locate_their_owner_unless_asked():
    layout = {"thing_locates_owner": {"pods2": True, "phone2": False}}
    assert persons.locates_owner(layout, "watch", "watch") and persons.locates_owner(layout, "meg", "cat")
    assert not persons.locates_owner(layout, "pods", "headphones")
    assert not persons.locates_owner(layout, "bag", "bag") and not persons.locates_owner(layout, "x", None)
    assert persons.locates_owner(layout, "pods2", "headphones")      # switched on for this pair
    assert not persons.locates_owner(layout, "phone2", "phone")      # switched off for this phone


def test_when_nothing_moves_the_latest_to_arrive_speaks_not_the_watch_on_its_charger():
    # The watch has sat on the nightstand since last night; the phone came
    # downstairs an hour ago. Neither is moving now.
    watch = thing("watch", "watch", still_for=9 * 3600, zone="Master Bedroom", spot="Alex Bedside Table")
    phone = thing("phone", "phone", still_for=3600, zone="Morning Room")
    assert persons.pick([watch, phone], NOW, 120)["ent"] == "phone"
    # A phone just carried somewhere keeps it ahead too.
    assert persons.pick([watch, thing("phone", "phone")], NOW, 120)["ent"] == "phone"


def test_settled_since_counts_metres_not_room_names_and_ignores_one_stray_fix():
    here = ("Up", 5.0, 5.0)
    pts = [(0, "Down", 1.0, 1.0), (200, "Up", 20.0, 5.0), (400, "Up", 20.0, 6.0),  # elsewhere for minutes
           (600, "Up", 5.5, 5.0), (700, "Up", 5.2, 4.8),                           # arrived
           (720, "Down", 9.0, 5.0), (760, "Down", 9.0, 5.0),                       # a minute a floor down: noise
           (800, "Up", 5.1, 5.1)]
    assert persons.settled_since(pts, here) == 600
    assert persons.settled_since([], here) is None
    assert persons.settled_since([(0, "Down", 5.0, 5.0)], here) is None



def test_arrival_survives_a_restart_with_a_late_history_and_a_wrong_floor_blip(monkeypatch):
    """What happened on 2026-09-19: after a restart the history had not loaded on
    the first cycle, the watch was placed a floor down for a minute, and every
    thing looked freshly arrived - so the watch on its charger won on class."""
    sextant._arrivals.clear()
    layout = {"floor": [{"name": "Up", "scale": 100.0}, {"name": "Down", "scale": 100.0}]}
    night = 1000.0                       # when the watch really came to rest
    answers = {"ready": False}

    def history(hass, ent, floor, x, y, now):
        return night if answers["ready"] and floor == "Up" else None

    monkeypatch.setattr(sextant, "_history_arrival", history)
    at_table = {"floor": "Up", "cords": [500.0, 500.0]}
    downstairs = {"floor": "Down", "cords": [900.0, 400.0]}
    t = 50_000.0
    # First cycle after the restart: history not loaded yet.
    assert sextant._arrived_at(None, layout, "watch", at_table, t) == t
    # It loads; the next cycle corrects the provisional answer.
    answers["ready"] = True
    assert sextant._arrived_at(None, layout, "watch", at_table, t + 15) == night
    # A wrong-floor blip for a minute: not a move.
    for dt in (30, 45, 60, 75):
        assert sextant._arrived_at(None, layout, "watch", downstairs, t + dt) == night
    assert sextant._arrived_at(None, layout, "watch", at_table, t + 90) == night
    # Really carried downstairs (over two minutes): a new arrival, from when it left.
    for dt in (100, 160, 230):
        got = sextant._arrived_at(None, layout, "watch", downstairs, t + dt)
    assert got == t + 100
    sextant._arrivals.clear()


def test_a_thing_on_its_charger_does_not_speak_for_its_owner():
    now = NOW
    watch = {**thing("watch", "watch", still_for=60, zone="Master Bedroom"), "on_charger": True}
    phone = thing("phone", "phone", still_for=5000, zone="Kitchen")
    # The watch just arrived and outranks the phone on class - but it is charging.
    assert persons.pick([watch, phone], now, 300)["ent"] == "phone"
    assert persons.pick([{**watch, "on_charger": False}, phone], now, 300)["ent"] == "watch"
    # Charging and nothing else: nobody is placed by it.
    assert persons.pick([watch], now, 300) is None
    # And the sensor says why.
    why = persons.considered([watch, phone], now)
    assert why[0]["on_charger"] is True and "on_charger" not in why[1]


def test_a_full_watch_stays_on_its_charger_until_it_moves():
    # Charging: on, and the time is noted.
    assert persons.still_on_charger(True, 100, None, 200) == (True, 200)
    # The sensor reads NotCharging at the charge limit, the watch has not moved: still on.
    assert persons.still_on_charger(False, 100, 200, 5000) == (True, 200)
    # It arrived somewhere after it last charged: on a wrist again.
    assert persons.still_on_charger(False, 300, 200, 5000) == (False, 200)
    # A reading that lags a watch carried off at 250 (charging since 200) does not hold it where it lands.
    assert persons.still_on_charger(True, 250, 200, 200) == (True, 200)
    assert persons.still_on_charger(False, 250, 200, 5000) == (False, 200)
    # Never seen charging, or no arrival to go by: not on a charger.
    assert persons.still_on_charger(False, 100, None, 5000) == (False, None)
    # "Charged" is not "charging": it holds a watch that has not moved since, and lets go of one that has
    assert not persons.charging_now("Charged") and persons.charging_now("Charging") and not persons.charging_now(None)
    assert persons.still_on_charger(False, 100, 200, 5000, full=True) == (True, 5000)
    assert persons.still_on_charger(False, 300, 200, 250, full=True) == (False, 250)
    assert persons.still_on_charger(False, 300, 200, 150, full=True) == (False, 200)
    assert persons.still_on_charger(False, 100, None, 250, full=True) == (True, 250)
    assert persons.still_on_charger(False, None, 200, 5000) == (False, 200)


def test_what_counts_as_on_the_charger():
    for s in ("Charging", "charging", "Charged", "Full", "on", " Charging "):
        assert persons.on_charger(s), s
    for s in ("Not Charging", "NotCharging", "not_charging", "Discharging", "off", "unavailable", "unknown", "", None, 42):
        assert not persons.on_charger(s), s


def test_a_long_silence_ends_the_stay_but_a_restart_does_not():
    from sextant import history
    assert persons.GAP_DROPOUT == history.GAP_DROPOUT
    here = ("Ground", 1.0, 1.0)
    # Here at 0..600 s, unheard for an hour, back in the same place from 4200 s.
    gone = [(t, "Ground", 1.0, 1.0, 0) for t in range(0, 601, 60)]
    gone += [(4200, "Ground", 1.0, 1.0, persons.GAP_DROPOUT), (4260, "Ground", 1.0, 1.0, 0)]
    assert persons.settled_since(gone, here) == 4200
    # The same with a two-minute restart in the middle: one stay from 0 s.
    restart = [(t, "Ground", 1.0, 1.0, 0) for t in range(0, 601, 60)]
    restart += [(720, "Ground", 1.0, 1.0, persons.GAP_DROPOUT), (780, "Ground", 1.0, 1.0, 0)]
    assert persons.settled_since(restart, here) == 0
    # Points without a gap column behave as before.
    assert persons.settled_since([p[:4] for p in gone], here) == 0


def test_considered_stays_the_same_while_nobody_moves():
    # A count of minutes would change every minute and write a recorder row
    # each time; when they arrived does not.
    phone = thing("phone", "phone", still_for=600, spot="Couch")
    assert persons.considered([phone], NOW) == persons.considered([phone], NOW + 3600)
    # No position to measure a stay from: arrival reads as "now" every cycle.
    assert persons.considered([{**phone, "arrived": NOW}], NOW)[0]["here_since"] is None
    assert persons.considered([{**phone, "arrived": None}], NOW)[0]["here_since"] is None


def test_a_person_who_owns_only_pet_tags_is_a_pet_and_gets_a_pets_device():
    by_person = {"person.leela": ["leela_tag"], "person.alex": ["alex_phone", "leela_spare"], "person.empty": []}
    classes = {"leela_tag": "cat", "leela_spare": "cat", "alex_phone": "phone"}
    assert persons.pet_persons(by_person, classes) == {"person.leela"}
    assert persons.device_model(True) == "Pet" and persons.device_model(False) == "Person"


def test_a_thing_beyond_every_room_reads_outside():
    best = {"ent": "primrose", "zone": "Kitchen", "floor": "Ground Floor", "outside": True}
    state, attrs = persons.states(best)["sextant_person_location"]
    assert state == "Outside" and attrs["kind"] == "outside" and attrs["via"] == "primrose"


def test_should_ask_gps_once_per_quiet_spell():
    ask = persons.should_ask_gps
    assert ask("quiet", False, NOW - 130, None)
    assert not ask("quiet", False, NOW - 130, NOW - 130)  # already asked this spell
    assert ask("quiet", False, NOW - 130, NOW - 500)  # heard again since, quiet again
    assert not ask("here", False, NOW - 30, None)
    assert not ask("away", False, NOW - 1000, None)
    assert not ask("quiet", True, NOW - 130, None)
    assert not ask("quiet", False, None, None)


def test_room_changes_need_two_cycles_and_compare_floor():
    from sextant import persons
    K, O, H1, H2 = ("Kitchen", "G"), ("Office", "G"), ("Hall", "G"), ("Hall", "U")
    base, pend = {"a": K, "b": K, "c": H1, "gone": K}, {}
    now = {"a": O, "b": K, "c": H2, "d": K, "pet": O}
    base, pend, ev = persons.room_changes(base, pend, now, pets=("pet",))
    assert ev == [] and pend == {"a": O, "c": H2} and base["a"] == K and "gone" not in base and "pet" not in base
    base, pend, ev = persons.room_changes(base, pend, now, pets=("pet",))
    assert [e[1]["person"] for e in ev] == ["a", "c"] and ev[1][1]["from_floor"] == "G" and ev[1][1]["floor"] == "U"
    assert base["a"] == O and pend == {}
    # a stray fix then back: nothing
    base, pend, ev = persons.room_changes(base, {}, {**now, "a": K}, pets=("pet",))
    base, pend, ev = persons.room_changes(base, pend, now, pets=("pet",))
    assert ev == [] and base["a"] == O
    # leaving and arriving make no room change
    base, pend, ev = persons.room_changes(base, {}, {**now, "a": None}, pets=("pet",))
    base, pend, ev = persons.room_changes(base, pend, {**now, "a": None}, pets=("pet",))
    assert ev == [] and base["a"] is None


def test_keep_since_holds_the_persons_time_across_a_device_handover():
    from sextant.persons import keep_since
    prev = {"floor": "Up", "room": "Office", "spot": "Desk", "since": 100.0, "spot_since": 200.0}
    # The phone takes over from the watch: same room and spot, the phone's own times are later.
    a = keep_since(prev, {"floor": "Up", "room": "Office", "spot": "Desk", "since": 900.0, "spot_since": 950.0})
    assert (a["since"], a["spot_since"]) == (100.0, 200.0)
    # Off the spot, still in the room: the room time stays, the spot time is the new one.
    b = keep_since(prev, {"floor": "Up", "room": "Office", "spot": None, "since": 900.0, "spot_since": 950.0})
    assert (b["since"], b["spot_since"]) == (100.0, 950.0)
    # A new room: the new times.
    c = keep_since(prev, {"floor": "Up", "room": "Hall", "spot": None, "since": 900.0})
    assert c["since"] == 900.0
    assert keep_since(None, {"room": "Hall", "since": 5.0})["since"] == 5.0
    # Away and back to the same room: the held fix's times are from before this visit home.
    d = keep_since(prev, {"floor": "Up", "room": "Office", "spot": "Desk", "since": 900.0, "spot_since": 950.0}, arrived=800.0)
    assert (d["since"], d["spot_since"]) == (900.0, 950.0)


def test_has_exit_finds_the_rooms_outside_door():
    layout = {"floor": [{"name": "Ground", "zones": [{"entity_id": "Laundry Room", "exit": True}, {"entity_id": "Kitchen"},
                                                     {"entity_id": "Void", "exit": True, "no_go": True}]}]}
    assert persons.has_exit(layout, "Ground", "Laundry Room")
    assert not persons.has_exit(layout, "Ground", "Kitchen")
    assert not persons.has_exit(layout, "Ground", "Void")
    assert not persons.has_exit(layout, "Upper", "Laundry Room")
    assert not persons.has_exit(None, "Ground", "Laundry Room")
    # Out fast: the room still held is the Kitchen, the last fix already in the Laundry Room.
    assert persons.held_by_exit(layout, {"floor": "Ground", "zone": "Kitchen", "zone_raw": "Laundry Room"})
    assert persons.held_by_exit(layout, {"floor": "Ground", "zone": "Laundry Room"})
    assert not persons.held_by_exit(layout, {"floor": "Ground", "zone": "Kitchen", "zone_raw": "Kitchen"})
    # Held outside: the location reads Outside, out since the last sighting.
    out = persons.fuse(None, [], "quiet", {"ent": "phone", "zone": "Laundry Room", "floor": "Ground", "outside": True, "since": 100.0},
                       None, [])
    state, attrs = out["sextant_person_location"]
    assert state == "Outside" and attrs["kind"] == "outside" and attrs["since"] == 100.0 and attrs["source"] == "held"


def test_slept_in_is_the_room_with_most_of_the_night_and_survives_a_restart():
    import json
    from datetime import datetime, timezone
    from sextant import runtime
    tz = timezone.utc
    at = lambda h, m=0, d=20: datetime(2026, 11, d, h, m, tzinfo=tz).timestamp()  # noqa: E731
    bed, sofa = ("Bedroom", "Second Floor"), ("Great Room", "Ground Floor")
    t = persons.sleep_tally(None, sofa, at(21, 50), tz, 22, 6)
    assert t is None, "before the night: nothing counted"
    for m in range(0, 60, 5):                       # 22:00-23:00 on the sofa
        t = persons.sleep_tally(t, sofa, at(22, m), tz, 22, 6)
    t = persons.sleep_tally(t, bed, at(23, 0), tz, 22, 6)
    saved = json.loads(json.dumps(runtime.snapshot(at(23, 30), sleep={"person.alex": t})))
    t = runtime.restore(saved, at(2, 0, 21))["sleep"]["person.alex"]   # down until 2 am: the gap counts 5 min at most
    for m in range(0, 240, 5):                      # 02:00-05:55 in bed
        t = persons.sleep_tally(t, bed, at(2 + m // 60, m % 60, 21), tz, 22, 6)
    state, attrs = persons.sleep_state(t)
    assert state == "Bedroom" and attrs["night"] == "2026-11-20" and attrs["floor"] == "Second Floor" and attrs["tonight"]
    assert attrs["minutes"] == {"Bedroom (Second Floor)": 240, "Great Room (Ground Floor)": 60}
    t = persons.sleep_tally(t, sofa, at(9, 0, 21), tz, 22, 6)         # morning: last night stands
    assert persons.sleep_state(t)[0] == "Bedroom" and not persons.sleep_state(t)[1]["tonight"]
    t = persons.sleep_tally(t, sofa, at(22, 0, 21), tz, 22, 6)        # the next night starts afresh
    assert persons.sleep_state(t) == ("unknown", {"night": "2026-11-21", "floor": None, "tonight": True, "minutes": {}})
    # Same name on two floors: two rooms. Equal hours: off.
    t = persons.sleep_tally(None, bed, at(23, 0), tz, 22, 6)
    t = persons.sleep_tally(t, ("Bedroom", "Ground Floor"), at(23, 5), tz, 22, 6)
    t = persons.sleep_tally(t, None, at(23, 6), tz, 22, 6)
    assert persons.sleep_state(t)[1]["minutes"] == {"Bedroom (Second Floor)": 5, "Bedroom (Ground Floor)": 1}
    assert persons.sleep_tally(None, bed, at(23, 0), tz, 22, 22) is None
    # A damaged save drops that person, not the restore.
    bad = {"saved_at": at(23, 0), "things": {}, "sleep": {"a": {"night": "x", "rooms": {"R (F)": 10 ** 400}, "places": {}}, "b": "junk"}}
    assert runtime.restore(bad, at(23, 1))["sleep"] == {}


def test_the_last_charge_is_read_from_the_sensors_history():
    from datetime import datetime, timezone
    from types import SimpleNamespace as S
    at = lambda h: datetime(2026, 11, 21, h, tzinfo=timezone.utc)   # noqa: E731
    rows = [S(state="NotCharging", last_changed=at(3)), S(state="Charging", last_changed=at(4)),
            S(state="NotCharging", last_changed=at(5)), S(state="unavailable", last_changed=at(8))]
    began = persons.last_charge_began(rows)
    assert began == at(4).timestamp()
    # the watch sat down at 03:59, charged at 04:00 and stopped at its limit: still on the puck
    assert persons.still_on_charger(False, at(4).timestamp() - 60, began, 0)[0] is True
    full = rows[:2] + [S(state="Full", last_changed=at(6)), S(state="NotCharging", last_changed=at(7))]
    assert persons.last_charge_began(full) == at(4).timestamp()     # Charging then Full is one charge
    assert persons.last_charge_began(rows[:1]) is None and persons.last_charge_began(None) is None


def test_a_dog_unheard_with_her_collar_at_home_is_outside():
    gps = {"zone": "home", "latitude": 1.0, "longitude": 2.0, "gps_accuracy": 5, "tracker": "device_tracker.collar"}
    out = persons.fuse(None, [], "away", None, gps, [], dog=True)
    assert out["sextant_person_location"][0] == "Outside" and out["sextant_person_location"][1]["kind"] == "outside"
    assert out["sextant_person_room"][0] == "Outside"
    assert persons.fuse(None, [], "away", None, gps, [])["sextant_person_location"][0] == "home"      # a cat or a person
    away = {**gps, "zone": "not_home"}
    assert persons.fuse(None, [], "away", None, away, [], dog=True)["sextant_person_location"][0] == "away"


def test_a_phone_in_a_spot_beats_a_watch_just_across_the_room_line():
    # Both on the couch, which backs onto the Foyer line: the watch's fix lands
    # a metre and a half off, in the Foyer; the phone reads the Couch spot.
    phone = {**thing("phone", "phone", still_for=3600, spot="Couch"), "xy_m": (13.0, 5.0), "conf": 0.5}
    watch = {**thing("watch", "watch", still_for=3600, zone="Foyer"), "xy_m": (13.0, 6.5), "conf": 0.6}
    assert persons.pick([phone, watch], NOW, 120)["ent"] == "phone"
    # Farther apart than SPOT_NEAR_M they are not in the same place: the watch speaks.
    far = {**watch, "xy_m": (13.0, 7.1)}
    assert persons.pick([phone, far], NOW, 120)["ent"] == "watch"
    # The watch walked off a minute ago and the phone stayed: the watch speaks.
    walked = {**watch, "arrived": NOW - 60}
    assert persons.pick([phone, walked], NOW, 120)["ent"] == "watch"
    # Another floor, a watch in its own spot, a phone on its charger, no position: no change.
    assert persons.pick([phone, {**watch, "floor": "Second Floor"}], NOW, 120)["ent"] == "watch"
    assert persons.pick([phone, {**watch, "sub_zone": "Bench"}], NOW, 120)["ent"] == "watch"
    assert persons.pick([{**phone, "on_charger": True}, watch], NOW, 120)["ent"] == "watch"
    assert persons.pick([{**phone, "xy_m": None}, watch], NOW, 120)["ent"] == "watch"
    # A thing read as outside the house stays outside.
    assert persons.pick([phone, {**watch, "outside": True}], NOW, 120)["ent"] == "watch"
