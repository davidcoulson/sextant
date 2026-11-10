"""The learned per-thing range scale (_range_ratio / _learn_range_scale)."""
import math

import pytest

import sextant

SCALE = 50.0  # px per metre
PROXIES = [(0, 0), (10, 0), (10, 10), (0, 10), (5, 5), (2, 8)]
THING = (4.0, 6.0)


@pytest.fixture(autouse=True)
def _clean():
    sextant._range_scale.clear()
    yield
    sextant._range_scale.clear()


def _weighted(error, applied):
    out = []
    for px, py in PROXIES:
        r = math.hypot(px - THING[0], py - THING[1]) * error * applied * SCALE
        out.append((px * SCALE, py * SCALE, r, 1.0, r))
    return out


def _run(error, apply, cycles=400):
    for _ in range(cycles):
        applied = sextant._range_scale.get("tag", 1.0) if apply else 1.0
        weighted = _weighted(error, applied)
        fix = sextant.trilaterate(weighted)
        sextant._learn_range_scale("tag", sextant._range_ratio(fix, weighted, SCALE), 1.0, applied)
    return sextant._range_scale.get("tag", 1.0)


@pytest.mark.parametrize("error", [1.4, 0.75])
def test_applied_scale_walks_off_a_uniform_range_error(error):
    assert _run(error, apply=True) == pytest.approx(1.0 / error, rel=0.05)


def test_unapplied_scale_still_reports_the_error_direction():
    assert _run(1.4, apply=False) < 0.9


def test_true_ranges_leave_the_scale_alone():
    assert _run(1.0, apply=True) == pytest.approx(1.0, abs=0.01)


def test_scale_is_clamped_and_needs_four_readings():
    assert _run(3.0, apply=True) == sextant.RANGE_SCALE_MIN
    weighted = _weighted(1.4, 1.0)[:3]
    assert sextant._range_ratio(sextant.trilaterate(weighted), weighted, SCALE) is None


def test_off_by_default_and_saved_with_the_gains():
    sextant._range_scale["tag"] = 0.8
    assert sextant._applied_range_scale({}, "tag") == 1.0
    assert sextant._applied_range_scale({"tuning": {"range_auto_scale": True}}, "tag") == 0.8
    assert sextant._fp_gain_snapshot()["range_scale"] == {"tag": 0.8}
    sextant._range_scale.clear()
    sextant._restore_fp_gains({"range_scale": {"tag": 0.8, "wild": 9, "bad": "x"}})
    assert sextant._range_scale == {"tag": 0.8, "wild": sextant.RANGE_SCALE_MAX}
