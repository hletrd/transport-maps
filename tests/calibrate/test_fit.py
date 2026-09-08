"""The fit must recover coefficients it was given, or it is not a fit."""

import numpy as np
import polars as pl
import pytest

from transport_maps.calibrate import fit


def test_recovers_known_airborne_coefficients():
    rng = np.random.default_rng(0)
    distances = rng.uniform(200, 12_000, 4_000)
    airborne = 25.0 + 60.0 * distances / 800.0 + rng.normal(0, 4.0, len(distances))
    df = pl.DataFrame({"distance_km": distances, "airborne_min": airborne})

    penalty, cruise = fit.fit_airborne(df)
    assert penalty == pytest.approx(25.0, abs=3.0)
    assert cruise == pytest.approx(800.0, abs=25.0)


def test_recovers_known_frequency_coefficients():
    rng = np.random.default_rng(2)
    n = 3_000
    d = rng.uniform(200, 12_000, n)
    dep = rng.choice(["large", "medium", "small"], n)
    arr = rng.choice(["large", "medium", "small"], n)
    truth = {"large": 1.0, "medium": 0.55, "small": 0.25}
    f = (42.0 * np.array([truth[s] for s in dep]) * np.array([truth[s] for s in arr])
         * d ** -0.35)
    df = pl.DataFrame({"distance_km": d, "dep_size": dep, "arr_size": arr,
                       "flights_per_week": f})

    base, decay, weights = fit.fit_frequency(df)
    assert base == pytest.approx(42.0, rel=0.15)
    assert decay == pytest.approx(-0.35, abs=0.05)
    assert weights["medium"] == pytest.approx(0.55, rel=0.15)
    assert weights["small"] == pytest.approx(0.25, rel=0.15)


def test_holdout_mae_is_small_on_clean_data():
    rng = np.random.default_rng(1)
    d = rng.uniform(200, 12_000, 2_000)
    df = pl.DataFrame({"distance_km": d, "airborne_min": 25.0 + 60.0 * d / 800.0})
    _, _, mae = fit.fit_airborne_with_holdout(df)
    assert mae < 2.0


def test_a_sample_that_is_not_flight_data_is_refused():
    """A negative distance coefficient means longer flights take less time.
    Silently returning a negative cruise speed would poison every edge weight.
    """
    d = np.linspace(200, 12_000, 500)
    df = pl.DataFrame({"distance_km": d, "airborne_min": 1000.0 - 0.05 * d})
    with pytest.raises(RuntimeError, match="not flight data"):
        fit.fit_airborne(df)
