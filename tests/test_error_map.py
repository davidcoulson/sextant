"""Predicted-error map for the Advice page: noise fit, field, stars, purple."""
import math

import numpy as np

import sextant  # noqa: F401
from sextant import error_map


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
