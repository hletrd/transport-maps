"""Regress model coefficients from observed flights.

Reads flight records, writes only numbers. The samples themselves never reach
`dist/` -- see tests/test_licence_firewall.py. That firewall was built for the
commercial providers' terms; adsb.lol is ODbL, so redistribution would in fact
be permitted with attribution, but the separation is kept because it costs
nothing and keeps a proprietary sample safe to use later.
"""

from __future__ import annotations

import numpy as np
import polars as pl

HOLDOUT_FRACTION = 0.2


def fit_airborne(df: pl.DataFrame) -> tuple[float, float]:
    """Least squares on `airborne_min = penalty + 60 * distance_km / cruise_kmh`.

    Returns (penalty_min, cruise_kmh).
    """
    d = df["distance_km"].to_numpy()
    y = df["airborne_min"].to_numpy()
    design = np.column_stack([np.ones_like(d), d])
    (intercept, slope), *_ = np.linalg.lstsq(design, y, rcond=None)
    if slope <= 0:
        raise RuntimeError(
            "non-positive distance coefficient: the sample says flights get "
            "faster the further they go, which means it is not flight data"
        )
    return float(intercept), float(60.0 / slope)


def fit_airborne_with_holdout(df: pl.DataFrame) -> tuple[float, float, float]:
    """Fit on 80%, report mean absolute error on the held-out 20%."""
    shuffled = df.sample(fraction=1.0, shuffle=True, seed=0)
    cut = int(len(shuffled) * (1.0 - HOLDOUT_FRACTION))
    train, test = shuffled[:cut], shuffled[cut:]
    penalty, cruise = fit_airborne(train)
    predicted = penalty + 60.0 * test["distance_km"].to_numpy() / cruise
    mae = float(np.abs(predicted - test["airborne_min"].to_numpy()).mean())
    return penalty, cruise, mae


def fit_frequency(df: pl.DataFrame) -> tuple[float, float, dict[str, float]]:
    """Fit `flights_per_week = base * w[dep] * w[arr] * distance_km ** decay`.

    Linear in log space. `large` is the reference category with weight fixed at
    1.0, which keeps the design matrix full rank.
    """
    sizes = ("medium", "small")
    log_f = np.log(df["flights_per_week"].to_numpy())
    log_d = np.log(np.maximum(df["distance_km"].to_numpy(), 1.0))

    columns = [np.ones_like(log_d), log_d]
    for size in sizes:
        dep = (df["dep_size"].to_numpy() == size).astype(float)
        arr = (df["arr_size"].to_numpy() == size).astype(float)
        columns.append(dep + arr)

    coefficients, *_ = np.linalg.lstsq(np.column_stack(columns), log_f, rcond=None)
    base = float(np.exp(coefficients[0]))
    decay = float(coefficients[1])
    weights = {"large": 1.0}
    for offset, size in enumerate(sizes):
        weights[size] = float(np.exp(coefficients[2 + offset]))
    return base, decay, weights
