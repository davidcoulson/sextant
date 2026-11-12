"""fit_point is the plain-float twin of the array solver; they must agree."""

import numpy as np

from sextant import solver_numpy


def test_fit_point_matches_the_array_solver():
    rng = np.random.default_rng(1)
    for case in range(200):
        n = int(rng.integers(3, 14))
        px, py = rng.uniform(0, 15, n), rng.uniform(0, 15, n)
        tx, ty = rng.uniform(1, 14, 2)
        pr = np.hypot(px - tx, py - ty) * rng.lognormal(0, 0.3, n)
        pr[rng.random(n) < 0.15] *= 3
        sw = 1 / (1 + pr)
        # Every other case is unbounded, as trilaterate() is without a floor outline.
        bounds = ([0.0, 0.0], [15.0, 15.0]) if case % 2 else ([-np.inf] * 2, [np.inf] * 2)
        starts = [(px.mean(), py.mean()), (px[0], py[0]), (0.0, 0.0)]

        def fun(X):
            return sw * (np.hypot(px - X[0], py - X[1]) - pr)

        def jac(X):
            dx, dy = X[0] - px, X[1] - py
            d = np.maximum(np.hypot(dx, dy), 1e-9)
            return np.column_stack((sw * dx / d, sw * dy / d))

        want = solver_numpy.least_squares_bounded_soft_l1(
            fun, starts[0], jac, bounds, f_scale=0.3, extra_starts=starts[1:]
        )
        got = solver_numpy.fit_point(
            px.tolist(), py.tolist(), pr.tolist(), sw.tolist(), starts[0], bounds, 0.3, extra_starts=starts[1:]
        )
        assert got.success == want.success
        assert abs(got.cost - want.cost) < 1e-9
        np.testing.assert_allclose(got.x, want.x, atol=1e-5)


def test_fit_point_survives_nan_and_overflow():
    bad = solver_numpy.fit_point([0.0, 1.0, float("nan")], [0.0, 1.0, 2.0], [1.0] * 3, [1.0] * 3, (0.5, 0.5), ([0, 0], [5, 5]), 0.3)
    assert not bad.success
    solver_numpy.fit_point([0.0, 1e200, 3.0], [0.0, 1.0, 1e200], [1.0] * 3, [1e150] * 3, (0.5, 0.5), ([-1e300] * 2, [1e300] * 2), 0.3)
