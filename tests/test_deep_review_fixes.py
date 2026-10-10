"""Regression tests for the deep-review fixes: input guards, layout checks, limits."""
import math
import types

import sextant
from sextant import layout_check, ws


def test_placed_needs_finite_x_and_y():
    assert sextant._placed({"cords": {"x": 1.0, "y": 2}})
    for cords in (None, {}, {"x": 1.0}, {"x": float("nan"), "y": 1.0}, {"x": True, "y": 1.0}, [1, 2]):
        assert not sextant._placed({"cords": cords}), cords


def test_finite_xy():
    assert sextant._finite_xy((1.0, 2.0, 3.0))
    assert not sextant._finite_xy((math.nan, 2.0))
    assert not sextant._finite_xy((None, 2.0))
    assert not sextant._finite_xy(())


def test_layout_check_accepts_a_normal_layout():
    layout = {"floor": [{"name": "Ground", "scale": 100.0, "level": 0,
                         "receivers": [{"entity_id": "kitchen", "cords": {"x": 1, "y": 2, "r": 3}}],
                         "zones": [{"entity_id": "Kitchen", "cords": [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 5, "y": 5}]}],
                         "subzones": [], "pins": [{"name": "A", "cords": {"x": 1, "y": 1}}]}],
              "thing_names": {"phone": "Phone"}, "tuning": {}}
    assert layout_check.layout_problem(layout) is None


def test_layout_check_refuses_what_would_break_a_cycle():
    bad = [
        [],
        {"floor": {}},
        {"floor": [{"scale": 1}]},
        {"floor": [{"name": "G", "scale": float("nan")}]},
        {"floor": [{"name": "G", "scale": -1}]},
        {"floor": [{"name": "G", "receivers": [[1, 2]]}]},
        {"floor": [{"name": "G", "receivers": [{"cords": {"x": float("inf"), "y": 1}}]}]},
        {"floor": [{"name": "G", "zones": [{"cords": [{"x": 0, "y": "a"}]}]}]},
        {"floor": [{"name": "G", "zones": [{"cords": "nope"}]}]},
        {"floor": [{"name": "G", "zones": [{"cords": [{"x": 0, "y": 0}] * (layout_check.MAX_VERTICES + 1)}]}]},
        {"floor": [], "thing_names": ["x"]},
        {"floor": [], "tuning": 3},
    ]
    for layout in bad:
        assert layout_check.layout_problem(layout) is not None, layout


def test_person_trackers_are_capped():
    hass = types.SimpleNamespace(data={})
    errors = []
    conn = types.SimpleNamespace(send_error=lambda i, c, m: errors.append(m), send_result=lambda *a: None)
    msg = {"id": 1, "type": "sextant/person/trackers/set", "person": "person.d",
           "trackers": [f"device_tracker.t{i}" for i in range(ws.MAX_PERSON_TRACKERS + 1)]}
    import asyncio
    asyncio.run(ws.ws_person_trackers_set(hass, conn, msg))
    assert errors and "At most" in errors[0]
