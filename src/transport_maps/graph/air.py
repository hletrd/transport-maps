"""Flight block-time and expected-wait models."""

import tomllib
from dataclasses import dataclass

from transport_maps import config

MINUTES_PER_WEEK = 7 * 24 * 60
# Sentinel weight for a route with no service. Large but finite so Dijkstra
# never selects it while still keeping the matrix free of infinities.
NO_SERVICE = 10**7


@dataclass(frozen=True)
class Calibration:
    climb_descent_penalty_min: float
    cruise_kmh: float
    taxi_out_min: dict[str, float]
    taxi_in_min: dict[str, float]
    frequency_base: float
    frequency_decay: float
    frequency_size_weight: dict[str, float]
    access_min: dict[str, dict[str, float]]
    egress_min: dict[str, dict[str, float]]
    connection_min: dict[str, float]


def load_calibration(path=None) -> Calibration:
    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    return Calibration(
        climb_descent_penalty_min=raw["airborne"]["climb_descent_penalty_min"],
        cruise_kmh=raw["airborne"]["cruise_kmh"],
        taxi_out_min=raw["taxi_out_min"],
        taxi_in_min=raw["taxi_in_min"],
        frequency_base=raw["frequency"]["base"],
        frequency_decay=raw["frequency"]["decay"],
        frequency_size_weight=raw["frequency"]["size_weight"],
        access_min=raw["access_min"],
        egress_min=raw["egress_min"],
        connection_min=raw["connection_min"],
    )


def block_time_min(distance_km: float, dep_size: str, arr_size: str, cal: Calibration) -> int:
    """Gate-to-gate time in whole minutes."""
    airborne = cal.climb_descent_penalty_min + 60.0 * distance_km / cal.cruise_kmh
    total = cal.taxi_out_min[dep_size] + airborne + cal.taxi_in_min[arr_size]
    return round(total)


def expected_wait_min(flights_per_week: float) -> int:
    """"Leave now" semantics: expected wait is half the headway."""
    if flights_per_week <= 0:
        return NO_SERVICE
    headway = MINUTES_PER_WEEK / flights_per_week
    return round(headway / 2.0)


MIN_FLIGHTS_PER_WEEK = 0.5

# Distance at which the gravity model's distance term stops rising. The decay
# exponent is negative, so `distance_km ** decay` DIVERGES as distance goes to
# zero: with the old 1 km floor, the 2.8 km Westray-Papa Westray hop came out
# at 6,041 flights/week and a 1-minute expected wait, against a real ~14/week
# and ~6 hours. This is the mirror image of the shallow-decay defect already
# fixed at the long-haul end -- the model was simply unguarded on the other
# side.
#
# 400 km is equivalently a 412 flights/week ceiling for a large-large pair
# (12 minutes' expected wait), which no real route beats by much. It also sits
# below every anchor the coefficients were fitted to, so none of them moves:
# ICN-CJU 361.9/wk, ICN-NRT 116.8/wk, ICN-LHR 13.6/wk. Do NOT raise it past
# ~450: at 500 km the knee clamps Seoul-Jeju and drags a fitted anchor from
# 361.9 down to 322.3.
KNEE_KM = 400.0


def frequency_model(dep_size: str, arr_size: str, distance_km: float, cal: Calibration) -> float:
    """Estimated weekly frequency for a route known to exist.

    Bounded at BOTH ends: `KNEE_KM` caps the short-range blow-up,
    `MIN_FLIGHTS_PER_WEEK` floors the ultra-long-haul tail (it first binds at
    14,395 km for a small-small pair, so the two never interact).
    """
    w = cal.frequency_size_weight
    freq = (
        cal.frequency_base
        * w[dep_size]
        * w[arr_size]
        * max(distance_km, KNEE_KM) ** cal.frequency_decay
    )
    return max(freq, MIN_FLIGHTS_PER_WEEK)
