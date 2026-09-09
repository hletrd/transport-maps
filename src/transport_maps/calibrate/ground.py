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
