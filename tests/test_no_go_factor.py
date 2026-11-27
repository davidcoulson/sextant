from shapely.geometry import box

import sextant as s


def test_no_go_penalty_ramps_in_from_the_edge():
    polys = [("v", box(0, 0, 400, 400), 0, True)]  # 4 m square void at 100 px/m
    f = lambda x: s._no_go_factor((x, 200), polys, 100)
    assert f(-10) == 1.0                      # outside
    assert f(50) == 1.0                       # 0.5 m in: within the fit's error of the walkway
    assert abs(f(200) - s.NO_GO_CONF_PENALTY) < 1e-9    # 2 m in: plainly over the void
    assert 1.0 > f(112.5) > s.NO_GO_CONF_PENALTY
    assert s._no_go_factor((50, 200), polys, None) == s.NO_GO_CONF_PENALTY
    assert s._no_go_factor((50, 200), [("r", box(0, 0, 400, 400), 0, False)], 100) == 1.0


def test_depth_is_from_the_whole_voids_edge():
    # Two 1.4 m strips overlapping by 0.2 m: 1.3 m deep together, not 0.7 m each.
    strips = [("a", box(0, 0, 140, 1000), 0, True), ("b", box(120, 0, 260, 1000), 0, True)]
    assert s._no_go_factor((130, 500), strips, 100) < 0.5
    # A hole (a landing inside the void) is an edge too, and a MultiPolygon must not raise.
    ring = box(0, 0, 1000, 1000).difference(box(300, 300, 700, 700))
    assert s._no_go_factor((250, 500), [("r", ring, 0, True)], 100) == 1.0
    multi = box(0, 0, 100, 100).union(box(500, 0, 900, 400))
    assert s._no_go_factor((700, 200), [("m", multi, 0, True)], 100) < 0.2
