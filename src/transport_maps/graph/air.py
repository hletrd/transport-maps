"""Flight block-time and expected-wait models."""

import tomllib
from dataclasses import dataclass

from transport_maps import config

# "Expected wait is half the headway" is not an air fact; ferries charge it
# too. Re-exported here so `air.MINUTES_PER_WEEK` / `air.NO_SERVICE` /
# `air.expected_wait_min` keep working for every existing caller and test.
from transport_maps.graph.headway import (  # noqa: F401
    MINUTES_PER_WEEK,
    NO_SERVICE,
    expected_wait_min,
)


@dataclass(frozen=True)
class Calibration:
    climb_descent_penalty_min: float
    cruise_kmh: float
    taxi_out_min: dict[str, float]
    taxi_in_min: dict[str, float]
    frequency_base: float
    frequency_decay: float
    frequency_size_weight: dict[str, float]
    processing_min: dict[str, float]
    disembark_min: dict[str, float]
    border_min: dict[str, float]
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
        processing_min=raw["processing_min"],
        disembark_min=raw["disembark_min"],
        border_min=raw["border_min"],
        connection_min=raw["connection_min"],
    )


def block_time_min(distance_km: float, dep_size: str, arr_size: str, cal: Calibration) -> int:
    """Gate-to-gate time in whole minutes."""
    airborne = cal.climb_descent_penalty_min + 60.0 * distance_km / cal.cruise_kmh
    total = cal.taxi_out_min[dep_size] + airborne + cal.taxi_in_min[arr_size]
    return round(total)


def load_frequency_bounds(path=None) -> tuple[float, float]:
    """calibration.toml [frequency] `knee_km` and `min_flights_per_week`.

    Both are bounds on the gravity model, not fits: calibration.toml says why
    each value was chosen. They lived here as literals until task B2
    (2026-10-02), with the same values; tests/test_calibration_moved.py pins
    them.
    """
    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)["frequency"]
    knee, floor = float(raw["knee_km"]), float(raw["min_flights_per_week"])
    if not (knee > 0 and floor > 0):
        raise ValueError(f"{path} [frequency] knee_km and min_flights_per_week must be "
                         f"positive; got {knee}, {floor}")
    return knee, floor


# Distance at which the gravity model's distance term stops rising, and the
# floor under its ultra-long-haul tail. Read once, at import.
KNEE_KM, MIN_FLIGHTS_PER_WEEK = load_frequency_bounds()


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
