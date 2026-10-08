"""The Wi-Fi signal field (field.py): wall counting, the fit, the grid."""
import math

import numpy as np

import sextant  # noqa: F401
from sextant import field

S = 100.0   # px per metre
A, B = "8c:ed:e1:00:de:ed", "28:70:4e:27:04:ed"


def _room(name, x0, y0, x1, y1):
    return {"entity_id": name, "poly": True, "cords": [{"x": x0 * S, "y": y0 * S}, {"x": x1 * S, "y": y0 * S},
                                                        {"x": x1 * S, "y": y1 * S}, {"x": x0 * S, "y": y1 * S}]}


def _layout(aps, second=False):
    ground = {"name": "Ground", "scale": S, "level": 0,
              "zones": [_room("West", 0, 0, 5, 5), _room("East", 5, 0, 10, 5)],
              "pins": [{"name": "P1", "cords": {"x": 0, "y": 0}}, {"name": "P2", "cords": {"x": 1000, "y": 0}},
                       {"name": "P3", "cords": {"x": 0, "y": 500}}],
              "access_points": [ap for ap in aps if ap["floor"] == "Ground"]}
    floors = [ground]
    if second:
        floors.append({"name": "Up", "scale": S, "level": 1, "zones": [_room("Bed", 0, 0, 10, 5)],
                       "pins": [{"name": "P1", "cords": {"x": 0, "y": 0}}, {"name": "P2", "cords": {"x": 1000, "y": 0}},
                                {"name": "P3", "cords": {"x": 0, "y": 500}}],
                       "access_points": [ap for ap in aps if ap["floor"] == "Up"]})
    for f in floors:
        for ap in f["access_points"]:
            ap.pop("floor", None)
    return {"floor": floors}


def test_walls_are_counted_once_where_two_rooms_meet():
    edges = field._edges([[(0, 0), (5, 0), (5, 5), (0, 5)], [(5, 0), (10, 0), (10, 5), (5, 5)]])
    got = field.walls_crossed(2.5, 2.5, [4.0, 7.5, 12.0], [2.5, 2.5, 2.5], edges)
    # Inside the room: none. Into the next room: the shared wall, drawn twice, is one.
    # Out of the house: that wall and the outside one.
    assert list(got) == [0, 1, 2]
    assert list(field.walls_crossed(0, 0, [1], [1], field._edges([]))) == [0]


def _truth(p, n, d, walls=0, wall_db=4.0):
    return p - 10 * n * math.log10(max(d, field.MIN_D_M)) - wall_db * walls


def test_the_fit_recovers_an_access_points_level_and_fall_off():
    layout = _layout([{"floor": "Ground", "mac": A, "cords": {"x": 250, "y": 250}}])
    squares = []
    for x in np.arange(0.5, 5, 1.0):
        for y in np.arange(0.5, 5, 1.0):
            d = math.hypot(x - 2.5, y - 2.5)
            squares.append(("Ground", x * S, y * S, A, _truth(-35, 2.6, d), 20))
    model = field.fit(layout, squares)
    ap = model["aps"][A]
    assert abs(ap["p"] - -35) < 1.5 and abs(ap["n"] - 2.6) < 0.25 and ap["samples"] == 25 and ap["rms"] < 0.5


def test_the_fit_learns_the_wall_loss_and_the_grid_shows_it():
    layout = _layout([{"floor": "Ground", "mac": A, "cords": {"x": 250, "y": 250}}])
    squares = []
    for x in np.arange(0.5, 10, 1.0):
        for y in np.arange(0.5, 5, 1.0):
            d = math.hypot(x - 2.5, y - 2.5)
            squares.append(("Ground", x * S, y * S, A, _truth(-35, 2.5, d, walls=1 if x > 5 else 0, wall_db=7.0), 20))
    model = field.fit(layout, squares)
    # Most of the way from the prior (4 dB) to the truth: the prior shrinks it.
    assert 5.0 < model["wall"] <= 7.5 and model["rms"] < 2.0
    g = field.grid(layout, model, "Ground", squares)
    assert g["step"] == field.GRID_M * S and g["aps"] == [A]
    vals = np.array(g["values"][A]).reshape(g["h"], g["w"])
    row = vals[5]   # y = 2.5 m
    # A drop across the wall at x = 5 m, beyond what distance alone explains.
    assert row[9] - row[11] > 5
    conf = np.array(g["conf"]).reshape(g["h"], g["w"])
    assert conf.max() == 100 and conf.min() >= 0


def test_priors_hold_an_access_point_nobody_has_measured():
    layout = _layout([{"floor": "Ground", "mac": A, "cords": {"x": 250, "y": 250}},
                      {"floor": "Ground", "mac": B, "cords": {"x": 750, "y": 250}}])
    squares = [("Ground", x * S, 250, A, _truth(-35, 2.5, abs(x - 2.5)), 10) for x in (0.5, 1.5, 3.5, 4.5)]
    model = field.fit(layout, squares)
    b = model["aps"][B]
    assert b["samples"] == 0 and b["rms"] is None
    assert abs(b["p"] - field.PRIOR_P_DBM) < 0.5 and abs(b["n"] - field.PRIOR_N) < 0.1
    g = field.grid(layout, model, "Ground", squares)
    assert set(g["aps"]) == {A, B}   # each is best somewhere
    # Confidence falls away from the measured squares.
    conf = np.array(g["conf"]).reshape(g["h"], g["w"])
    assert conf[5, 1] > 80 and conf[5, 19] < 30


def test_the_correction_pulls_the_field_to_what_was_measured():
    layout = _layout([{"floor": "Ground", "mac": A, "cords": {"x": 250, "y": 250}}])
    squares = [("Ground", x * S, y * S, A, _truth(-35, 2.5, math.hypot(x - 2.5, y - 2.5)), 20)
               for x in np.arange(0.5, 5, 1.0) for y in np.arange(0.5, 5, 1.0)]
    # One square reads 12 dB worse than the model would ever say (a fridge).
    squares = [s if (s[1], s[2]) != (450.0, 450.0) else (*s[:4], s[4] - 12, 20) for s in squares]
    model = field.fit(layout, squares)
    g = field.grid(layout, model, "Ground", squares)
    vals = np.array(g["values"][A]).reshape(g["h"], g["w"])
    plain = field.predict(layout, model, "Ground", [450.0], [450.0], A)[0]
    assert vals[9, 9] < plain - 4          # at the fridge, the field follows the measurement
    far = field.predict(layout, model, "Ground", [50.0], [50.0], A)[0]
    assert abs(vals[1, 1] - far) < 3       # away from it, the model stands


def test_another_floors_access_point_reaches_through_the_floor_with_its_loss():
    layout = _layout([{"floor": "Up", "mac": A, "cords": {"x": 250, "y": 250}},
                      {"floor": "Ground", "mac": B, "cords": {"x": 750, "y": 250}}], second=True)
    squares = []
    for x in np.arange(0.5, 10, 1.0):
        for y in np.arange(0.5, 5, 1.0):
            d_up = math.sqrt((x - 2.5) ** 2 + (y - 2.5) ** 2 + 9)
            squares.append(("Ground", x * S, y * S, A, _truth(-35, 2.5, d_up) - 18, 20))
            # Measured on its own floor too: without that, its level and the
            # floor's loss are one number, and the floor loss stays the prior.
            squares.append(("Up", x * S, y * S, A, _truth(-35, 2.5, math.hypot(x - 2.5, y - 2.5)), 20))
            squares.append(("Ground", x * S, y * S, B, _truth(-35, 2.5, math.hypot(x - 7.5, y - 2.5),
                                                               walls=1 if x < 5 else 0), 20))
    model = field.fit(layout, squares)
    assert 16.0 < model["floor"] <= 18.5   # most of the way from the prior (15 dB)
    g = field.grid(layout, model, "Ground", squares)
    assert A in g["values"] and B in g["values"]


def test_nothing_to_fit_or_draw():
    assert field.fit({"floor": [{"name": "Ground", "scale": S}]}, []) is None
    layout = _layout([{"floor": "Ground", "mac": A, "cords": {"x": 250, "y": 250}}])
    model = field.fit(layout, [])
    assert model["used"] == 0 and model["rms"] is None
    assert field.grid(layout, None, "Ground", []) is None
    assert field.grid(layout, model, "Nowhere", []) is None
    g = field.grid(layout, model, "Ground", [])
    assert g is not None and max(g["conf"]) == 0


def test_each_band_is_fitted_on_its_own_once_it_has_enough_squares():
    layout = _layout([{"floor": "Ground", "mac": A, "cords": {"x": 250, "y": 250}}])
    squares = []
    for x in np.arange(0.5, 10, 1.0):
        for y in np.arange(0.5, 5, 1.0):
            d = math.hypot(x - 2.5, y - 2.5)
            walls = 1 if x > 5 else 0
            # 2.4 GHz: strong, slow fall-off, a light wall. 5 GHz: weaker, faster, a heavy wall.
            squares.append(("Ground", x * S, y * S, A, _truth(-30, 2.2, d, walls, 3.0), 20, "2.4"))
            squares.append(("Ground", x * S, y * S, A, _truth(-38, 3.4, d, walls, 9.0), 20, "5"))
    models = field.fit_bands(layout, squares)
    assert sorted(models) == ["2.4", "5"]
    assert models["2.4"]["aps"][A]["n"] < models["5"]["aps"][A]["n"]
    assert models["2.4"]["wall"] < models["5"]["wall"]
    assert models["5"]["rms"] < 1.5 and models["2.4"]["rms"] < 1.5
    g = field.grid_bands(layout, models, "Ground", squares)
    assert g["aps"] == [f"{A}|2.4", f"{A}|5"]
    five = field.grid_bands(layout, models, "Ground", squares, "5")
    assert five["aps"] == [f"{A}|5"] and five["w"] == g["w"]
    assert field.grid_bands(layout, models, "Ground", squares, "6") is None


def test_too_few_squares_on_any_band_are_fitted_together():
    layout = _layout([{"floor": "Ground", "mac": A, "cords": {"x": 250, "y": 250}}])
    squares = [("Ground", x * S, 250, A, _truth(-35, 2.5, abs(x - 2.5)), 10, b)
               for x, b in ((0.5, "2.4"), (1.5, "5"), (3.5, None), (4.5, "2.4"))]
    models = field.fit_bands(layout, squares)
    assert list(models) == [field.MIXED] and models[field.MIXED]["used"] == 4
    assert field.grid_bands(layout, models, "Ground", squares)["aps"] == [f"{A}|mixed"]
    assert field.fit_bands({"floor": []}, squares) == {}
