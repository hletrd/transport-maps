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


def weekday_morning_utc(lon: float, today=None) -> str:
    """RFC 3339 UTC for 10:00 local SOLAR time (longitude / 15 h) on the next
    Tuesday at least two days out. Routes prices a future departure on typical
    traffic for that hour; solar time is within an hour of civil time almost
    everywhere, and 10:00 sits in the daytime plateau either side of it."""
    from datetime import UTC, datetime, timedelta

    today = today or datetime.now(UTC).date()
    day = today + timedelta(days=2)
    day += timedelta(days=(1 - day.weekday()) % 7)            # Tuesday
    local = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
    return (local - timedelta(hours=lon / 15.0)).strftime("%Y-%m-%dT%H:%M:%SZ")


def drive_times(client: httpx.Client, budget: RequestBudget, a: tuple[float, float],
                b: tuple[float, float], depart_utc: str) -> tuple[float, float] | None:
    """(typical-traffic minutes, free-flow minutes) between two points for a
    departure at `depart_utc`, from ONE call: TRAFFIC_AWARE returns both
    `duration` and `staticDuration`. None where Google has no route."""
    budget.take()
    body = {
        "origin": {"location": {"latLng": {"latitude": a[0], "longitude": a[1]}}},
        "destination": {"location": {"latLng": {"latitude": b[0], "longitude": b[1]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": depart_utc,
    }
    r = client.post(ENDPOINT, json=body, headers={
        "X-Goog-Api-Key": api_key(),
        "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters",
    }, timeout=TIMEOUT_S)
    r.raise_for_status()
    routes = r.json().get("routes")
    if not routes:
        return None
    sec = lambda v: float(str(v).rstrip("s")) / 60.0          # noqa: E731
    return sec(routes[0]["duration"]), sec(routes[0].get("staticDuration", routes[0]["duration"]))


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


# --- the structured model (rebuild 31) -----------------------------------------
#
# Two things one set of class speeds and one flat penalty could not say, both
# measured on ground_samples3.json and on the 2026-10-14 audit's pairs:
#
# * Free-flow speed depends on the country. Out of fold the rebuild-30 fit was
#   23% too slow on North American town journeys (median observed/predicted
#   0.81) and 6% too fast in Asia (1.06); by income group 0.85 (high) against
#   1.24 (low). A multiplier per World Bank income group (sources/countries
#   INCOME_GROUPS) carries it.
# * A built-up area's extent scales with its city. Twenty kilometres from any
#   city of 200,000 covered all of a town and none of the outer half of
#   London: the London -> LHR path ran 22 km of highway-graded cells at
#   54.6 km/h (23 min against Google's 45 free-flow). The penalty here is by
#   distance in the city's own built-up radius (sources/urban.
#   scaled_city_distance).
#
# A journey is kilometres per road class (6) per income group (4) per band,
# in two band sets: absolute km to the nearest city (DIST_BANDS_KM), for the
# old structure, and that distance in city radii (SCALED_BANDS).

N_INCOME = 4
#: Upper edges of the scaled-distance bands, in city built-up radii.
SCALED_BANDS = (0.5, 1.0, 1.5, 2.0, 3.0)
#: Classes whose speed an income multiplier scales. Roadless is walking pace
#: and local a published default; neither is fitted, so neither is scaled.
#: The motorway class (6, graph/ground.MOTORWAY_CLASS) is scaled or not as a
#: Structure says.
SCALED_CLASSES = (1, 2, 3, 4)
MOTORWAY = 6
#: Classes that count as highway for `highway_apart` and `income_split`.
HIGHWAY_CLASSES = (1, MOTORWAY)
#: The income group the multipliers are relative to (upper middle).
REFERENCE_INCOME = 1


def scaled_band_of(s: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.asarray(SCALED_BANDS), s, side="right")


def class_income_speeds(speeds: np.ndarray, mult: np.ndarray,
                        scaled: tuple[int, ...] = SCALED_CLASSES) -> np.ndarray:
    """(classes, N_INCOME) km/h: class speed times the income multiplier, for
    the classes in `scaled`; the others as given. `mult` is one row for every
    scaled class, or two: highways (HIGHWAY_CLASSES), then the rest."""
    speeds = np.asarray(speeds, dtype=float)
    v = np.repeat(speeds[:, None], N_INCOME, axis=1)
    mult = np.atleast_2d(np.asarray(mult, dtype=float))
    for c in scaled:
        if c < len(speeds):
            v[c] *= mult[0] if (c in HIGHWAY_CLASSES or len(mult) == 1) else mult[1]
    return v


#: Upper edges of the size classes of the city a cell's scaled distance is
#: measured to, by Natural Earth pop_max: under 1 M, 1-5 M, 5 M and over.
SIZE_BANDS = (1e6, 5e6)
N_SIZES = len(SIZE_BANDS) + 1


def size_band_of(pop: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.asarray(SIZE_BANDS), pop, side="right")


def predict_structured(km: np.ndarray, speeds: np.ndarray, mult: np.ndarray,
                       factor: np.ndarray, scaled: tuple[int, ...] = SCALED_CLASSES) -> np.ndarray:
    """Minutes per journey. `km` is (n, classes, N_INCOME, B), or (n,
    classes, N_INCOME, B, N_SIZES) with the city size class; `factor`
    (classes, B) or (classes, B, N_SIZES), the time multiplier per class and
    band (1 where uncongested)."""
    v = class_income_speeds(speeds, mult, scaled)
    if km.ndim == 5:
        f = factor if factor.ndim == 3 else np.repeat(factor[:, :, None], km.shape[4], axis=2)
        return 60.0 * (km * f[None, :, None, :, :] / v[None, :, :, None, None]).sum(axis=(1, 2, 3, 4))
    return 60.0 * (km * factor[None, :, None, :] / v[None, :, :, None]).sum(axis=(1, 2, 3))


class Structure:
    """A congestion structure over one band set: which bands are penalised,
    by how many factors, whether highways get their own, whether each city
    size class gets its own, whether income multipliers are fitted, and how
    the motorway class (6) is priced. `unpack` turns a parameter vector --
    log speeds of the fitted classes, log multipliers, log factors, then the
    end minutes -- into model arrays.

    Motorway options, for a 7-class sample: `motorway_income` scales class 6
    by the income multipliers like the others; `motorway_merged` gives it
    class 1's speed, which is the old model on the same paths. Class 6 is
    always penalised inside a city like the rest; `highway_apart` gives
    classes 1 and 6 their own factor."""

    def __init__(self, name: str, bands: str, groups: list[tuple[int, ...]],
                 income: bool, highway_apart: bool = False, sizes: bool = False,
                 ends: bool = False, income_split: bool = False, n_classes: int = 6,
                 motorway_income: bool = True, motorway_merged: bool = False) -> None:
        self.name, self.bands, self.groups = name, bands, groups
        self.income, self.highway_apart, self.sizes = income, highway_apart, sizes
        self.ends, self.income_split = ends, income_split
        self.n_classes = n_classes
        self.motorway_income, self.motorway_merged = motorway_income, motorway_merged
        self.n_bands = (len(DIST_BANDS_KM) if bands == "abs" else len(SCALED_BANDS)) + 1

    @property
    def free(self) -> list[int]:
        """The classes with a fitted speed of their own."""
        return [c for c in range(self.n_classes) if c not in FIXED_CLASSES
                and not (c == MOTORWAY and self.motorway_merged)]

    @property
    def scaled(self) -> tuple[int, ...]:
        mw = self.n_classes > MOTORWAY and (self.motorway_income or self.motorway_merged)
        return SCALED_CLASSES + ((MOTORWAY,) if mw else ())

    @property
    def n_factors(self) -> int:
        return len(self.groups) * (2 if self.highway_apart else 1) * (N_SIZES if self.sizes else 1)

    @property
    def n_income(self) -> int:
        return (N_INCOME - 1) * (2 if self.income_split else 1) if self.income else 0

    def n_params(self) -> int:
        return len(self.free) + self.n_income + self.n_factors + (1 if self.ends else 0)

    def end_minutes(self, theta: np.ndarray) -> float:
        """The fitted minutes every journey pays once, at its two ends -- 0
        unless the structure has them. Stored last in `theta`, log-free and
        bounded at 0 by fit_structured."""
        return float(theta[-1]) if self.ends else 0.0

    def unpack(self, theta: np.ndarray, fixed_kmh: np.ndarray):
        speeds = np.array(fixed_kmh, dtype=float)[: self.n_classes]
        free = self.free
        speeds[free] = np.exp(theta[: len(free)])
        if self.motorway_merged and self.n_classes > MOTORWAY:
            speeds[MOTORWAY] = speeds[1]
        k = len(free)
        mult = np.ones((2 if self.income_split else 1, N_INCOME))
        if self.income:
            others = [g for g in range(N_INCOME) if g != REFERENCE_INCOME]
            for row in range(len(mult)):
                mult[row, others] = np.exp(theta[k:k + N_INCOME - 1])
                k += N_INCOME - 1
        mult = mult if self.income_split else mult[0]
        f = np.exp(theta[k:k + self.n_factors])
        z = N_SIZES if self.sizes else 1
        factor = np.ones((self.n_classes, self.n_bands, z))
        per = len(self.groups) * z           # factors per class group (all, or highway)
        hw = [c for c in HIGHWAY_CLASSES if c < self.n_classes]
        for i, bands in enumerate(self.groups):
            for j in range(z):
                for b in bands:
                    factor[1:, b, j] = f[i * z + j]
                    if self.highway_apart:
                        factor[hw, b, j] = f[per + i * z + j]
        return speeds, mult, (factor if self.sizes else factor[:, :, 0])

    def predict(self, km: np.ndarray, theta: np.ndarray, fixed_kmh: np.ndarray) -> np.ndarray:
        """Minutes per journey under `theta`, end minutes included."""
        sp, mu, fa = self.unpack(theta, fixed_kmh)
        return predict_structured(km, sp, mu, fa, self.scaled) + self.end_minutes(theta)

    def describe(self, theta: np.ndarray, fixed_kmh: np.ndarray) -> str:
        speeds, mult, _factor = self.unpack(theta, fixed_kmh)
        k = len(self.free) + self.n_income
        f = np.exp(theta[k:k + self.n_factors])
        return (f"speeds {np.round(speeds, 1).tolist()} income x{np.round(mult, 3).tolist()} "
                f"factors {np.round(f, 2).tolist()} ends {self.end_minutes(theta):.1f} min")


def fit_structured(km: np.ndarray, observed_min: np.ndarray, st: Structure,
                   fixed_kmh: np.ndarray, weights: np.ndarray,
                   start: np.ndarray | None = None) -> np.ndarray:
    """Parameters minimising the weighted sum of squared log errors. Factors
    are bounded below at 1 (traffic does not make a road faster), speeds and
    multipliers are free."""
    from scipy.optimize import least_squares

    root_w = np.sqrt(weights)

    def residual(theta):
        pred = st.predict(km, theta, fixed_kmh)
        return root_w * np.log(np.maximum(pred, 1e-6) / observed_min)

    n = st.n_params()
    e = 1 if st.ends else 0
    guess = {1: 80.0, 2: 50.0, 3: 50.0, 4: 30.0, MOTORWAY: 95.0}
    x0 = (np.r_[np.log([guess[c] for c in st.free]), np.zeros(n - len(st.free))]
          if start is None else start)
    x0 = x0.copy()
    first = n - e - st.n_factors                   # factors, then the end minutes
    x0[first:n - e] = np.maximum(x0[first:n - e], 0.05)
    if e:
        x0[-1] = max(x0[-1], 5.0)
    lo = np.r_[np.full(first, -np.inf), np.zeros(st.n_factors + e)]
    sol = least_squares(residual, x0, bounds=(lo, np.full(n, np.inf)), method="trf")
    return sol.x


def cell_speeds_from_fit(fit: dict, classes: np.ndarray, income: np.ndarray,
                         band: np.ndarray, motorway_class: int = MOTORWAY) -> np.ndarray:
    """Per-cell km/h under a fit `calibrate_ground.py fit --out` wrote: class
    speed x income multiplier / the factor of the cell's class and scaled
    band. A fit from before the motorway class prices a motorway cell as the
    GRIP4 highway it was. For scripts/ground_pairs.py and for planning a
    sample on the paths a candidate would give."""
    speeds = np.array(fit["speeds"], dtype=float)
    cls = classes if len(speeds) > motorway_class else np.where(classes == motorway_class, 1, classes)
    scaled = tuple(fit.get("scaled_classes", SCALED_CLASSES))
    v = class_income_speeds(speeds, np.array(fit["income"]), scaled)
    return v[cls, income] / np.array(fit["factor"])[cls, band]
