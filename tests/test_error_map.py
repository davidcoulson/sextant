"""Predicted-error map for the Advice page: noise fit, field, stars, purple."""
import math

import numpy as np

import sextant  # noqa: F401
from sextant import advice, error_map


def _pair(tx, rx, d, ln_bias, n=8):
    # Constant samples: no jitter, so the pair's error is its bias alone.
    return (tx, rx, float(d), [d * math.exp(ln_bias)] * n)


def test_fewer_than_eight_pairs_use_the_defaults():
    out = error_map.fit_noise([("a", "b", 3.0, [3.1] * 10)] * 7)
    assert (out["a"], out["b"], out["calibrated"], out["pairs"]) == (0.6, 0.0, False, 7)
    assert error_map.fit_noise([])["factor"] == {}


def test_the_fit_recovers_a_known_noise_line():
    pairs = [_pair(f"t{d}", f"r{d}", d, 0.2 + 0.05 * d) for d in range(1, 13)]
    out = error_map.fit_noise(pairs)
    assert abs(out["a"] - 0.2) < 0.02 and abs(out["b"] - 0.05) < 0.005 and out["calibrated"]


def test_a_proxy_that_ranges_worse_gets_a_bigger_factor():
    pairs = [_pair(f"n{i}", f"n{i + 1}", d, 0.3) for i, d in enumerate(range(2, 12))]
    pairs += [_pair("bad", f"n{i}", d, 0.6) for i, d in enumerate((3, 5, 7, 9))]
    f = error_map.fit_noise(pairs)["factor"]
    assert 1.3 < f["bad"] <= error_map.K_MAX
    assert f["n9"] < 1.0


def test_pairs_without_a_true_distance_or_samples_are_skipped():
    out = error_map.fit_noise([("a", "b", 0.0, [3.0] * 8), ("a", "c", 3.0, []), ("a", "d", 3.0, [0.0, -1.0])])
    assert out["pairs"] == 0


def test_the_centre_of_four_proxies_beats_a_point_off_to_one_side():
    sq = [(0, 0, 1.0), (6, 0, 1.0), (0, 6, 1.0), (6, 6, 1.0)]
    e = error_map.error_field(np.array([3.0, 12.0]), np.array([3.0, 3.0]), sq, 0.3, 0.0)
    assert e[0] < e[1]


def test_two_proxies_or_fewer_in_range_hit_the_cap():
    e = error_map.error_field(np.array([0.0, 30.0]), np.array([0.0, 0.0]), [(1, 0, 1.0), (2, 0, 1.0)], 0.3, 0.0)
    assert e[1] == error_map.ERR_CAP_M and np.isfinite(e).all()


def _rect(name, x0, y0, x1, y1):
    return {"zone_id": name, "entity_id": name, "poly": True,
            "cords": [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]}


def _floor(receivers, zones, name="F"):
    return {"name": name, "scale": 100.0, "zones": zones,
            "receivers": [{"entity_id": s, "cords": {"x": x, "y": y}} for s, x, y in receivers]}


_NOISE = {"a": 0.3, "b": 0.0, "factor": {}}
_HALL3 = [("a", 450, 50), ("b", 750, 50), ("c", 600, 350)]
_THREE_ROOMS = [_rect("Left", 0, 0, 400, 400), _rect("Hall", 400, 0, 800, 400), _rect("Right", 800, 0, 1200, 400)]


def _near_wall(star, x0, y0, x1, y1, scale=100.0):
    x, y = star["x"], star["y"]
    return min(abs(x - x0), abs(x - x1), abs(y - y0), abs(y - y1)) <= advice.WALL_INSET_M * scale + 1


def test_an_empty_corner_room_gets_the_star():
    fl = _floor([("a", 50, 50), ("b", 350, 50), ("c", 200, 350)], [_rect("Hall", 0, 0, 400, 400), _rect("Far", 900, 0, 1300, 400)])
    out = error_map.floor_map(fl, _NOISE, {})
    assert out["stars"][0]["room"] == "Far" and _near_wall(out["stars"][0], 900, 0, 1300, 400)
    assert out["stars"][0]["gain_pct"] >= 3


def test_time_spent_moves_the_star():
    right = error_map.floor_map(_floor(_HALL3, _THREE_ROOMS), _NOISE, {("F", "Right"): 36000.0})
    left = error_map.floor_map(_floor(_HALL3, _THREE_ROOMS), _NOISE, {("F", "Left"): 36000.0})
    assert right["stars"][0]["room"] == "Right" and left["stars"][0]["room"] == "Left"


def test_no_star_below_three_percent_gain():
    ring = [(f"p{i}", x, y) for i, (x, y) in enumerate(
        [(x, 12) for x in range(12, 400, 40)] + [(x, 388) for x in range(12, 400, 40)]
        + [(12, y) for y in range(52, 360, 40)] + [(388, y) for y in range(52, 360, 40)])]
    out = error_map.floor_map(_floor(ring, [_rect("Hall", 0, 0, 400, 400)]), _NOISE, {})
    assert out["stars"] == []


def test_a_floor_without_proxies_says_it_needs_three():
    out = error_map.floor_map(_floor([], _THREE_ROOMS), _NOISE, {})
    assert out["stars"] == [] and "three proxies" in out["note"]
    assert set(out["err"]) == {error_map.ERR_CAP_M}
    two = error_map.floor_map(_floor(_HALL3[:2], _THREE_ROOMS), _NOISE, {})
    assert all(math.isfinite(v) for v in two["err"] + two["err_after"]) and (two["stars"] or two["note"])


def test_after_is_no_worse_than_before_and_the_grid_matches():
    out = error_map.floor_map(_floor(_HALL3, _THREE_ROOMS), _NOISE, {})
    g = out["grid"]
    assert len(out["err"]) == len(out["err_after"]) == g["w"] * g["h"] and g["step"] == 50.0
    assert all(b <= a + 1e-9 for a, b in zip(out["err"], out["err_after"]))
    assert g["x0"] == -100 + 25 and g["y0"] == -100 + 25   # 1 m margin, cell centres


def test_a_floor_without_scale_or_rooms_has_no_map():
    assert error_map.floor_map({"name": "X", "scale": None, "zones": _THREE_ROOMS, "receivers": []}, _NOISE, {}) is None
    assert error_map.floor_map(_floor(_HALL3, []), _NOISE, {}) is None


def test_room_seconds_caps_long_steps_and_skips_gaps():
    layout = {"floor": [_floor([], [_rect("Hall", 0, 0, 400, 400)])]}
    track = [(0.0, "F", 1.0, 1.0, 0), (3600.0, "F", 1.0, 1.0, 0), (3610.0, "F", 1.0, 1.0, 2), (3620.0, "F", 1.0, 1.0, 0),
             (3630.0, "F", 9.0, 9.0, 0), (3640.0, "Elsewhere", 1.0, 1.0, 0), (3650.0, "F", 1.0, 1.0, 1)]
    assert error_map.room_seconds(layout, {"cat": track}) == {("F", "Hall"): 620.0}
