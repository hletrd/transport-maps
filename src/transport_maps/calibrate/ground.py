"""Fit per-road-class ground speeds against sampled real driving journeys.

The model charges a cell's traversal at one speed per GRIP4 road class, so a
journey's predicted time is the sum over its path of `distance / speed[class]`.
That is LINEAR in the reciprocal speeds, which makes the fit an ordinary least
squares on the per-class distances rather than anything iterative:

    observed_minutes  ~  sum_c  distance_in_class_c / speed_c

Sampling notes, both learned the hard way:

* Google Routes returns NO driving route anywhere inside South Korea -- the
  mapping export restriction, not an error. Samples there come back empty and
  are dropped, so Korean cells inherit the globally fitted speeds.
* Requests are capped hard. A loop that silently retried could spend real money
  on a bug, so the cap is checked before every call rather than after.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import numpy as np

ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
# Enough to fit six speeds with a held-out set, and far inside the 10,000/month
# free allowance. Checked BEFORE each call.
MAX_REQUESTS = 4000
# A journey shorter than this is dominated by the endpoints rather than by the
# road classes crossed; longer than this and it would realistically be flown.
# Widened down from 25 km after the first run: journeys that long stay on
# trunk roads, so the sample saw 41.8% highway and 47.6% primary but only 3.0%
# tertiary and NO local road at all, leaving both unfittable. Short hops
# between small towns are what traverse the lower classes.
MIN_KM, MAX_KM = 8.0, 600.0
TIMEOUT_S = 20.0


class RequestBudget:
    """Refuses to exceed a fixed number of paid calls."""

    def __init__(self, limit: int = MAX_REQUESTS) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise RuntimeError(
                f"request budget of {self.limit} exhausted; refusing to spend more"
            )
        self.used += 1


def api_key() -> str:
    key = os.environ.get("GOOGLE_ROUTES_API_KEY")
    if not key:
        raise RuntimeError(
            "GOOGLE_ROUTES_API_KEY is not set; source ~/.config/transport-maps/env"
        )
    return key


def drive_minutes(client: httpx.Client, budget: RequestBudget,
                  a: tuple[float, float], b: tuple[float, float]) -> float | None:
    """Driving minutes between two points, or None where Google has no route."""
    budget.take()
    body = {
        "origin": {"location": {"latLng": {"latitude": a[0], "longitude": a[1]}}},
        "destination": {"location": {"latLng": {"latitude": b[0], "longitude": b[1]}}},
        "travelMode": "DRIVE",
    }
    r = client.post(ENDPOINT, json=body, headers={
        "X-Goog-Api-Key": api_key(),
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
    }, timeout=TIMEOUT_S)
    r.raise_for_status()
    routes = r.json().get("routes")
    if not routes:
        return None                      # South Korea, or genuinely unroutable
    return float(routes[0]["duration"].rstrip("s")) / 60.0


# A class needs this much sampled distance and this many journeys before its
# fitted speed means anything. Without the guard the first real run returned
# 58 km/h for ROADLESS terrain, from 103 km across 6 journeys -- a number that
# is not merely wrong but physically impossible, and which least squares was
# happy to produce because nothing asked whether the column had any support.
MIN_CLASS_KM = 2_000.0
MIN_CLASS_SAMPLES = 30


def fit_speeds(class_km: np.ndarray, observed_min: np.ndarray,
               n_classes: int = 6) -> np.ndarray:
    """Least squares for `speed[class]` from per-class distances and times.

    Solves for reciprocal speeds, which is where the model is linear, then
    inverts. A class the sample cannot speak to comes back as NaN; the caller
    keeps its existing value rather than adopting a fabricated one.
    """
    if class_km.shape[1] != n_classes:
        raise ValueError(f"expected {n_classes} class columns, got {class_km.shape[1]}")

    supported = ((class_km.sum(axis=0) >= MIN_CLASS_KM)
                 & ((class_km > 0).sum(axis=0) >= MIN_CLASS_SAMPLES))
    speeds = np.full(n_classes, np.nan)
    if not supported.any():
        return speeds

    # Fit EVERY column, then adopt only the supported ones. Dropping a column
    # from the design matrix leaves the time spent in that class unexplained,
    # and least squares pushes that error into whichever column remains --
    # which would corrupt the classes the sample DOES support. lstsq handles
    # the rank deficiency from an all-zero column by minimum norm.
    recip, *_ = np.linalg.lstsq(class_km, observed_min / 60.0, rcond=None)
    usable = supported & (recip > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        speeds[usable] = 1.0 / recip[usable]
    return speeds


def save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def sleep_between(seconds: float = 0.05) -> None:
    """Be a polite client; the free tier is not an invitation to hammer."""
    time.sleep(seconds)


# --- the structured fit (2026-10-14) ----------------------------------------
#
# The OLS above minimises squared MINUTES, so the longest journeys decide it.
# Over ground_samples2.json the shipped speeds leave journeys that are more
# than 30% tertiary at a median observed/predicted of 0.74 -- 26% too slow on
# exactly the trips that use those roads -- while the fit calls itself right
# overall (0.99). A travel-time map is read in ratios: ten minutes wrong on a
# half-hour trip matters as much as an hour on a five-hour one. So the fit
# below minimises squared RELATIVE error, and the urban penalty is fitted as
# a structure (which radius, which classes) rather than assumed.
#
# A journey is recorded as kilometres per road class (rows, 0 roadless .. 5
# local) per distance band from the nearest city of URBAN_POP_MIN or more
# (columns, DIST_BANDS_KM). A cell is "urban" under radius R exactly when its
# band's upper edge is <= R, so every radius on a band edge is fittable from
# one sample.

#: Upper edges of the distance-to-city bands, km; the last band is open.
DIST_BANDS_KM = (5.0, 10.0, 20.0, 40.0)
#: Classes the sample cannot support (roadless, local) keep their published
#: defaults and enter the fit as a known offset.
FIXED_CLASSES = (0, 5)


def band_of(d_km: np.ndarray) -> np.ndarray:
    """Distance band index (0 .. len(DIST_BANDS_KM)) for each distance."""
    return np.searchsorted(np.asarray(DIST_BANDS_KM), d_km, side="right")


def design(km: np.ndarray, radius_km: float, groups: np.ndarray,
           factors: np.ndarray) -> np.ndarray:
    """(n, 6) congestion-weighted kilometres per class.

    `km` is (n, 6, len(DIST_BANDS_KM) + 1). Bands within `radius_km` are urban
    and their kilometres are multiplied by `factors[groups[class]]`; roadless
    is never congested (graph/ground.cell_speed_kmh).
    """
    edges = np.r_[DIST_BANDS_KM, np.inf]
    urban_band = edges <= radius_km
    rural = km[:, :, ~urban_band].sum(axis=2)
    urban = km[:, :, urban_band].sum(axis=2)
    f = factors[groups].copy()
    f[0] = 1.0
    return rural + urban * f[None, :]


def fit_relative(km: np.ndarray, observed_min: np.ndarray, radius_km: float,
                 groups: np.ndarray, factors: np.ndarray,
                 fixed_kmh: np.ndarray) -> np.ndarray:
    """Free-flow speed per class minimising sum(((pred - obs) / obs) ** 2),
    for one congestion structure. Classes in FIXED_CLASSES keep `fixed_kmh`;
    a fitted class whose reciprocal comes back non-positive is NaN."""
    X = design(km, radius_km, groups, factors)
    free = [c for c in range(X.shape[1]) if c not in FIXED_CLASSES]
    offset = sum(X[:, c] / fixed_kmh[c] for c in FIXED_CLASSES) * 60.0
    w = 1.0 / observed_min
    target = (observed_min - offset) / 60.0
    recip, *_ = np.linalg.lstsq(X[:, free] * w[:, None], target * w, rcond=None)
    speeds = np.array(fixed_kmh, dtype=float)
    with np.errstate(divide="ignore"):
        speeds[free] = np.where(recip > 0, 1.0 / recip, np.nan)
    return speeds


def fit_log(km: np.ndarray, observed_min: np.ndarray, radius_km: float,
            groups: np.ndarray, factors: np.ndarray, fixed_kmh: np.ndarray,
            weights: np.ndarray | None = None) -> np.ndarray:
    """Free-flow speed per class minimising sum(log(pred / obs) ** 2).

    The error a reader of the map sees is a ratio, and squared log error is
    the one objective that treats 0.8x and 1.25x alike: squared relative
    error, `fit_relative`, rewards predicting low and came out 6-9% fast on
    ground_samples3.json. Started from `fit_relative`'s answer; classes in
    FIXED_CLASSES keep `fixed_kmh`. `weights` scale each journey's term
    (the caller balances journey kinds with them)."""
    from scipy.optimize import least_squares

    X = design(km, radius_km, groups, factors)
    free = [c for c in range(X.shape[1]) if c not in FIXED_CLASSES]
    offset = sum(X[:, c] / fixed_kmh[c] for c in FIXED_CLASSES) * 60.0
    start = fit_relative(km, observed_min, radius_km, groups, factors, fixed_kmh)[free]
    start = np.where(np.isfinite(start), start, 40.0)

    root_w = np.sqrt(weights) if weights is not None else 1.0

    def residual(log_v):
        pred = offset + (X[:, free] / np.exp(log_v)[None, :]).sum(axis=1) * 60.0
        return root_w * np.log(np.maximum(pred, 1e-6) / observed_min)

    sol = least_squares(residual, np.log(start), method="lm")
    speeds = np.array(fixed_kmh, dtype=float)
    speeds[free] = np.exp(sol.x)
    return speeds


def predict(km: np.ndarray, speeds: np.ndarray, radius_km: float, groups: np.ndarray,
            factors: np.ndarray) -> np.ndarray:
    """Predicted minutes per journey."""
    return (design(km, radius_km, groups, factors) / speeds[None, :]).sum(axis=1) * 60.0
