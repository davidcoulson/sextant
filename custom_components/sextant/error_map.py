"""Predicted position error per half-metre square, for the Advice page map.

The prediction is a port of the receiver placement advisor in Hogster/BPS
(custom_components/bps/placement.py, MIT licence, (c) Hogster):

- Ranging noise sigma(d) = d * (a + b*d) * k, fitted on proxy-to-proxy
  pairs: a pair's error is hypot(|ln(median / true)|, std(ln samples)).
  k is how much worse a proxy's own pairs are than the fitted line.
- The error at a point is the Cramer-Rao bound of 2-D ranging,
  sqrt(trace(J^-1)), J = sum(u u^T / sigma^2) over the floor's proxies in
  range: distance, count and spread around the point all count.

The metres are a pessimistic model figure; the colours rank places. Pure
numpy and shapely, so it is testable without Home Assistant.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

GRID_M = 0.5
MAX_RANGE_M = 15.0
MIN_D_M = 0.5
ERR_CAP_M = 8.0
DEFAULT_A, DEFAULT_B = 0.6, 0.0     # no calibration pairs to fit on
MIN_PAIRS_FOR_FIT = 8
K_MIN, K_MAX = 0.6, 2.0
JITTER_DEFAULT = 0.3                # ln jitter assumed for 5 samples or fewer


def fit_noise(pairs):
    """Noise line and per-proxy factor from (tx, rx, true_m, samples_m) pairs."""
    used = []
    for tx, rx, true_m, samples in pairs:
        s = [float(v) for v in samples or [] if v and v > 0]
        if not true_m or true_m <= 0 or not s:
            continue
        jit = float(np.std(np.log(s))) if len(s) > 5 else JITTER_DEFAULT
        bias = abs(math.log(float(np.median(s)) / true_m))
        used.append((tx, rx, float(true_m), math.hypot(bias, jit)))
    if len(used) < MIN_PAIRS_FOR_FIT:
        return {"a": DEFAULT_A, "b": DEFAULT_B, "factor": {}, "pairs": len(used), "calibrated": False}
    A = np.array([[1.0, p[2]] for p in used])
    y = np.array([p[3] for p in used])
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)
    a, b = max(float(a), 0.1), max(float(b), 0.0)
    ratios = defaultdict(list)
    for tx, rx, d, err in used:
        r = err / (a + b * d)
        ratios[tx].append(r)
        ratios[rx].append(r)
    factor = {k: float(np.clip(np.median(v), K_MIN, K_MAX)) for k, v in ratios.items()}
    return {"a": a, "b": b, "factor": factor, "pairs": len(used), "calibrated": True}


def _info(gx, gy, proxies, a, b):
    """Fisher terms (j00, j01, j11) at points gx, gy (metres).

    A proxy's x, y may be arrays broadcastable against gx: that tries many
    candidate spots at once.
    """
    j00 = np.zeros(np.broadcast(gx, gy).shape)
    j01 = np.zeros_like(j00)
    j11 = np.zeros_like(j00)
    for px, py, k in proxies:
        dx, dy = px - gx, py - gy
        d = np.maximum(np.hypot(dx, dy), MIN_D_M)
        sig = d * (a + b * d) * k
        w = np.where(d <= MAX_RANGE_M, 1.0 / sig ** 2, 0.0)
        ux, uy = dx / d, dy / d
        j00 = j00 + w * ux * ux
        j01 = j01 + w * ux * uy
        j11 = j11 + w * uy * uy
    return j00, j01, j11


def _err(j00, j01, j11):
    det = j00 * j11 - j01 ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.sqrt((j00 + j11) / det)
    return np.minimum(np.where(np.isfinite(e), e, ERR_CAP_M), ERR_CAP_M)


def error_field(gx, gy, proxies, a, b):
    """Predicted error (m) at points gx, gy (metres); proxies [(x, y, k)]."""
    return _err(*_info(gx, gy, proxies, a, b))
