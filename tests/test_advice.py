"""Placement advice (sextant.advice.advise): per-room issues and suggested wall spots."""
import sextant  # noqa: F401
from sextant import advice


def _rect(name, x0, y0, x1, y1):
    return {"zone_id": name, "entity_id": name, "poly": True,
            "cords": [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]}


def _layout(receivers, zones):
    return {"floor": [{"name": "F", "scale": 100.0, "zones": zones,
                       "receivers": [{"entity_id": s, "cords": {"x": x, "y": y}} for s, x, y in receivers]}]}


def _selftest(rows):
    return {"receivers": [{"entity": s, "floor": "F", "room": room, "error_m": e, "heard_by": 5} for s, room, e in rows]}


def test_a_room_with_no_proxy_gets_a_wall_spot_inside_it():
    layout = _layout([("a", 50, 50), ("b", 350, 50), ("c", 200, 350)], [_rect("Hall", 0, 0, 400, 400), _rect("Closet", 400, 0, 700, 400)])
    out = advice.advise(layout, _selftest([("a", "Hall", 1.0), ("b", "Hall", 1.2), ("c", "Hall", 0.8)]))
    closet = next(r for r in out["rooms"] if r["room"] == "Closet")
    assert closet["issue"] == "no proxy" and closet["add"] >= 1
    x, y = closet["spots"][0]["x"], closet["spots"][0]["y"]
    assert 400 <= x <= 700 and 0 <= y <= 400
    # An outlet is on a wall: the spot sits just inside the room's edge.
    assert min(abs(x - 400), abs(x - 700), abs(y - 0), abs(y - 400)) <= advice.WALL_INSET_M * 100 + 1
    assert out["rooms"][0]["room"] == "Closet"  # worst first
    assert out["summary"]["to_add"] >= 1


def test_a_well_covered_well_measured_room_is_fine():
    layout = _layout([("a", 20, 20), ("b", 380, 20), ("c", 200, 380), ("d", 20, 380)], [_rect("Hall", 0, 0, 400, 400)])
    out = advice.advise(layout, _selftest([("a", "Hall", 1.0), ("b", "Hall", 1.2), ("c", "Hall", 0.8), ("d", "Hall", 1.1)]))
    hall = out["rooms"][0]
    assert hall["issue"] == "ok" and hall["add"] == 0 and hall["proxies"] == 4 and hall["median_m"] == 1.05


def test_one_bad_proxy_among_good_ones_is_called_out_not_papered_over():
    layout = _layout([("a", 20, 20), ("b", 380, 20), ("c", 200, 380), ("d", 20, 380)], [_rect("Hall", 0, 0, 400, 400)])
    out = advice.advise(layout, _selftest([("a", "Hall", 1.0), ("b", "Hall", 6.5), ("c", "Hall", 0.8), ("d", "Hall", 1.1)]))
    hall = out["rooms"][0]
    assert hall["issue"] == "weak proxy" and hall["worst"] == "b" and hall["add"] == 0 and "b" in hall["note"]


def test_a_long_room_with_all_proxies_at_one_end_gets_spots_at_the_other():
    # 12 m x 3 m room, three proxies bunched in the first 2 m: the far end has its third proxy 10 m away.
    layout = _layout([("a", 20, 20), ("b", 180, 20), ("c", 100, 280)], [_rect("Corridor", 0, 0, 1200, 300)])
    out = advice.advise(layout, _selftest([("a", "Corridor", 2.5), ("b", "Corridor", 2.8), ("c", "Corridor", 2.4)]))
    corr = out["rooms"][0]
    assert corr["issue"] in ("coverage", "one-sided") and 1 <= corr["add"] <= advice.MAX_ADD
    assert max(s["x"] for s in corr["spots"]) > 400  # at least one spot well into the uncovered end
    assert corr["covered"] < 0.9 and corr["third_proxy_m"] > advice.TARGET_3RD_M


def test_unplaced_proxies_are_passed_through_and_floors_without_scale_skipped():
    layout = _layout([], [_rect("Hall", 0, 0, 400, 400)])
    layout["floor"].append({"name": "Unscaled", "scale": None, "zones": [_rect("X", 0, 0, 10, 10)], "receivers": []})
    out = advice.advise(layout, {"receivers": []}, unplaced=[{"slug": "kitchen_s3_f249cc", "name": "Kitchen S3 f249cc"}])
    assert out["unplaced"][0]["slug"] == "kitchen_s3_f249cc" and out["unplaced"][0]["suggest"]["room"] == "Hall"
    assert [r["floor"] for r in out["rooms"]] == ["F"] and out["rooms"][0]["issue"] == "no proxy"


def test_a_room_without_an_outline_and_a_proxy_without_a_place_are_left_out_not_fatal():
    # Both pass the layout check: None is "not drawn", an empty object "not placed".
    layout = _layout([], [_rect("Hall", 0, 0, 400, 400), {"zone_id": "Attic", "entity_id": "Attic", "cords": None}])
    layout["floor"][0]["receivers"] = [{"entity_id": "spare", "cords": {}}]
    out = advice.advise(layout, {"receivers": []})["rooms"]
    assert [(r["room"], r["proxies"]) for r in out] == [("Hall", 0)]


def test_two_bad_proxies_among_three_are_both_named():
    layout = _layout([("a", 20, 20), ("b", 380, 20), ("c", 200, 380)], [_rect("Jamie", 0, 0, 400, 400)])
    out = advice.advise(layout, _selftest([("a", "Jamie", 0.7), ("b", "Jamie", 7.0), ("c", "Jamie", 4.7)]))
    room = out["rooms"][0]
    assert room["issue"] == "weak proxy" and room["weak"] == ["b"]
    # Errors that are merely bad everywhere are "noisy" and get one far-wall spot for a fourth opinion.
    out = advice.advise(layout, _selftest([("a", "Jamie", 4.1), ("b", "Jamie", 4.9), ("c", "Jamie", 4.7)]))
    room = out["rooms"][0]
    assert room["issue"] == "noisy" and room["add"] == 1 and len(room["spots"]) == 1


def test_a_resting_place_with_no_pin_near_is_reported():
    layout = _layout([], [_rect("Den", 0, 0, 400, 400), _rect("Hall", 400, 0, 800, 400)])
    den = [(t, "F", 1.0, 1.0, 0) for t in range(0, 3 * 3600 + 1, 60)]                 # three hours at (1 m, 1 m)
    hall = [(t, "F", 6.0, 2.0, 0) for t in range(4 * 3600, 9 * 3600 + 1, 60)]         # an hour unheard, then five in the Hall
    out = advice.pin_gaps(layout, {"cat": den + hall}, {"cat": [("F", 6.5, 2.0)]})    # the Hall place has a pin 0.5 m away
    assert [(r["entity"], r["room"], r["hours"], r["x"], r["y"], r["nearest_pin_m"]) for r in out] == [("cat", "Den", 3.0, 100.0, 100.0, 5.6)]
    both = advice.pin_gaps(layout, {"cat": den + hall}, {})
    assert [(r["room"], r["hours"], r["nearest_pin_m"]) for r in both] == [("Hall", 5.0, None), ("Den", 3.0, None)]   # most hours first
    # Places with a pin, and floors no longer on the plan, do not use up the thing's two rows.
    attic = [(t, "Attic", 1.0, 1.0, 0) for t in range(10 * 3600, 20 * 3600 + 1, 60)]
    desk = [(t, "F", 3.0, 3.0, 0) for t in range(21 * 3600, 25 * 3600 + 1, 60)]
    bed = [(t, "F", 7.0, 3.5, 0) for t in range(26 * 3600, 32 * 3600 + 1, 60)]
    out = advice.pin_gaps(layout, {"cat": den + hall + attic + desk + bed}, {"cat": [("F", 6.5, 2.0), ("F", 7.0, 3.0)]})
    assert [(r["room"], r["hours"]) for r in out] == [("Den", 4.0), ("Den", 3.0)]


def test_time_between_two_resting_places_is_counted_once():
    layout = _layout([], [_rect("Den", 0, 0, 800, 800)])
    # Ten hours at one place, two between, ten at the next: on one grid the
    # two hours fall in with the first place, on a shifted grid with the second.
    a = [(t, "F", 0.1, 0.1, 0) for t in range(0, 10 * 3600, 60)]
    mid = [(t, "F", 1.1, 1.1, 0) for t in range(10 * 3600, 12 * 3600, 60)]
    b = [(t, "F", 2.1, 2.1, 0) for t in range(12 * 3600, 22 * 3600 + 1, 60)]
    out = advice.pin_gaps(layout, {"cat": a + mid + b}, {})
    assert [r["hours"] for r in out] == [12.0, 10.0]


def test_short_stays_silences_and_unknown_floors_are_not_resting_places():
    layout = _layout([], [_rect("Den", 0, 0, 400, 400)])
    hour = [(t, "F", 1.0, 1.0, 0) for t in range(0, 3601, 60)]
    assert advice.pin_gaps(layout, {"cat": hour}, {}) == []                             # under REST_MIN_HOURS
    quiet = [(0, "F", 1.0, 1.0, 0), (5 * 3600, "F", 1.0, 1.0, 0)]
    assert advice.pin_gaps(layout, {"cat": quiet}, {}) == []                            # five hours unheard is not a stay
    dropout = [(t, "F", 1.0, 1.0, 2) for t in range(0, 4 * 3600, 300)]
    assert advice.pin_gaps(layout, {"cat": dropout}, {}) == []                          # nor are points across dropouts
    gone = [(t, "Attic", 1.0, 1.0, 0) for t in range(0, 4 * 3600, 60)]
    assert advice.pin_gaps(layout, {"cat": gone}, {}) == []                             # a floor no longer on the plan


def test_a_used_room_that_needs_something_comes_before_an_unused_one():
    # The Closet has no proxy, the worse issue; the Corridor is poorly covered, and is where people are.
    layout = _layout([("a", 20, 20), ("b", 180, 20), ("c", 100, 280)], [_rect("Corridor", 0, 0, 1200, 300), _rect("Closet", 0, 300, 300, 600)])
    selftest = _selftest([("a", "Corridor", 2.5), ("b", "Corridor", 2.8), ("c", "Corridor", 2.4)])
    assert [r["room"] for r in advice.advise(layout, selftest)["rooms"]] == ["Closet", "Corridor"]
    # Time Outside is on no plan: the share is of the time in the rooms listed.
    usage = {"hours": 48.0, "rooms": {("F", "Corridor"): (3600.0, 3), ("F", "Outside"): (7200.0, 0)}}
    out = advice.advise(layout, selftest, unplaced=[{"slug": "spare", "name": "Spare"}], usage=usage)
    corridor, closet = out["rooms"]
    assert (corridor["room"], corridor["time_share"], corridor["bounces"]) == ("Corridor", 1.0, 3) and out["usage_hours"] == 48.0
    # A room the log never names has no data, which is not zero.
    assert (closet["room"], closet["time_share"], closet["bounces"]) == ("Closet", None, None)
    assert out["unplaced"][0]["suggest"]["room"] == "Corridor"   # the one spare proxy goes where people are


def test_room_use_is_read_from_the_person_log(tmp_path):
    from sextant import person_log
    lines = [{"t": t, "p": p, "place": place} for p, t, place in [
        ("jo", 0, ["Den", "F"]), ("jo", 30, ["Hall", "F"]), ("jo", 60, ["Den", "F"]),      # Den, Hall and back in 30 s: a bounce
        ("jo", 90, None),                                                                  # in no room: no time anywhere
        ("sam", 0, ["Den", "F"]), ("sam", 30, ["Hall", "F"]), ("sam", 500, ["Den", "F"]),  # back after two minutes: two moves
    ]]
    person_log.append(str(tmp_path), lines, 48, now=1000.0)
    use = advice.room_usage(person_log.rows(str(tmp_path)))
    # Seconds until the person's next line, so a faster cycle adds no time; sam's 470 s in the Hall with no line is cut to the cap.
    assert use["rooms"] == {("F", "Den"): (90.0, 1), ("F", "Hall"): (30.0 + advice.USE_STEP_MAX_S, 1)}
    assert [r["t"] for r in person_log.rows(str(tmp_path), since=400)] == [500]
    assert advice.room_usage([]) == {"hours": 0.0, "rooms": {}}


def test_lines_the_room_use_cannot_read_are_left_out_not_fatal(tmp_path):
    from sextant import person_log
    # Lines from before a line had a place say nothing of rooms and do not stretch the window.
    old = [{"t": 0, "p": "jo"}, {"t": 3600, "p": "jo"}]
    odd = [{"t": 7200, "p": "jo", "place": ["Den"]}, {"t": 7200, "place": ["Den", "F"]}, {"t": "x", "p": "jo", "place": None},
           {"t": 10 ** 400, "p": "jo", "place": None}]
    new = [{"t": 7200, "p": "jo", "place": ["Den", "F"]}, {"t": 10800, "p": "jo", "place": ["Den", "F"]}]
    assert advice.room_usage(old + odd + new) == {"hours": 1.0, "rooms": {("F", "Den"): (advice.USE_STEP_MAX_S, 0)}}
    # The reader passes over a line with no time, and never opens an hour's file from before the window.
    (tmp_path / "1970-01-01T00Z.jsonl").write_text('{"t":99999,"p":"jo","place":null}\n')
    # Bytes that are not text (a power cut mid-write) cost their own line and no other.
    (tmp_path / "1970-01-01T02Z.jsonl").write_bytes(b'{"t":null,"p":"jo"}\n[1]\n\xff\xfe{"t":7250}\n{"t":7300,"p":"jo","place":null}\n')
    assert [r["t"] for r in person_log.rows(str(tmp_path), since=7200)] == [7300]
