"""The ground fit must recover speeds it was given, and refuse to overspend."""

import numpy as np
import pytest

from transport_maps.calibrate import ground


def test_recovers_known_speeds_from_per_class_distances():
    rng = np.random.default_rng(0)
    truth = np.array([5.0, 95.0, 70.0, 50.0, 38.0, 30.0])
    km = rng.uniform(0, 40, size=(600, 6))
    hours = (km / truth).sum(axis=1)
    got = ground.fit_speeds(km, hours * 60.0)
    assert np.allclose(got, truth, rtol=0.02), got


def test_a_class_absent_from_the_sample_is_nan_not_invented():
    rng = np.random.default_rng(1)
    truth = np.array([5.0, 95.0, 70.0, 50.0, 38.0, 30.0])
    km = rng.uniform(0, 40, size=(400, 6))
    km[:, 0] = 0.0                      # never traversed
    hours = (km / truth).sum(axis=1)
    got = ground.fit_speeds(km, hours * 60.0)
    assert np.isnan(got[0]), "invented a speed for a class with no coverage"
    assert np.allclose(got[1:], truth[1:], rtol=0.02)


def test_the_request_budget_is_enforced_before_spending():
    b = ground.RequestBudget(limit=3)
    for _ in range(3):
        b.take()
    with pytest.raises(RuntimeError, match="budget"):
        b.take()
    assert b.used == 3, "a refused call must not count as spent"


def test_a_missing_key_is_an_explicit_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_ROUTES_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_ROUTES_API_KEY"):
        ground.api_key()


def test_an_empty_route_list_is_none_not_zero(monkeypatch):
    """Google answers 200 with {} inside South Korea. Reading that as a
    zero-minute journey would drag every fitted speed toward infinity."""
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {}
    class FakeClient:
        def post(self, *a, **k): return FakeResponse()
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "x")
    got = ground.drive_minutes(FakeClient(), ground.RequestBudget(), (0, 0), (1, 1))
    assert got is None


def test_a_barely_sampled_class_is_refused_not_fitted():
    """The first real run returned 58 km/h for ROADLESS terrain.

    It came from 103 km across 6 journeys out of 1,383, and least squares was
    happy to produce it because nothing asked whether the column had support.
    A physically impossible speed is worse than no answer.
    """
    rng = np.random.default_rng(3)
    truth = np.array([5.0, 95.0, 70.0, 50.0, 38.0, 30.0])
    km = rng.uniform(5, 40, size=(800, 6))
    km[:, 0] = 0.0
    km[:6, 0] = 17.0                      # 102 km across 6 journeys, as observed
    km[:, 5] = 0.0                        # local never traversed
    hours = (km / truth).sum(axis=1)
    got = ground.fit_speeds(km, hours * 60.0)
    assert np.isnan(got[0]), f"fitted a speed for roadless from 6 samples: {got[0]}"
    assert np.isnan(got[5]), "fitted a speed for a class with no distance at all"
    assert np.allclose(got[1:5], truth[1:5], rtol=0.05), got


def test_the_urban_penalty_covers_exactly_the_bands_inside_its_radius():
    """A journey of 1 km in every distance band and class: at radius 10 the
    two bands within 10 km are penalised and nothing further out is, roadless
    never is, and the highway can carry its own factor.

    Mutation performed and reverted: `edges <= radius_km` made `<` (the band
    ending AT the radius dropped) -> RED.
    """
    import numpy as np

    from transport_maps.calibrate import ground as gfit

    km = np.ones((1, 6, len(gfit.DIST_BANDS_KM) + 1))
    groups = np.array([0, 0, 1, 1, 1, 1])
    x = gfit.design(km, 10.0, groups, np.array([1.5, 3.0]))[0]
    n = km.shape[2]
    assert x[0] == n                              # roadless: never congested
    assert x[1] == (n - 2) + 2 * 1.5              # highway: two urban bands at 1.5
    assert (x[2:] == (n - 2) + 2 * 3.0).all()     # the rest at 3.0
    assert gfit.band_of(np.array([0.0, 4.9, 5.0, 39.9, 40.0, 900.0])).tolist() == [0, 0, 1, 3, 4, 4]


def test_the_structured_fit_recovers_known_speeds_income_factor_and_ends():
    """Synthetic journeys priced by a known model come back as that model:
    class speeds, the income multipliers, the built-up factor and the end
    minutes -- the four things scripts/calibrate_ground.py fits at once.

    Mutations performed and reverted, each RED: drop the end minutes from
    fit_structured's residual; apply the income multiplier to roadless too.
    """
    rng = np.random.default_rng(0)
    n, bands = 400, len(ground.SCALED_BANDS) + 1
    km = np.zeros((n, 6, ground.N_INCOME, bands))
    for j in range(n):
        g = rng.integers(0, ground.N_INCOME)
        for c in (1, 2, 3, 4):
            km[j, c, g, rng.integers(0, bands)] = rng.uniform(0, 60)
        km[j, 0, g, bands - 1] = rng.uniform(0, 2)
    st = ground.Structure("t", "scaled", [(0, 1)], income=True, ends=True)
    fixed = np.array([5.0, np.nan, np.nan, np.nan, np.nan, 25.0])
    truth = np.r_[np.log([75.0, 60.0, 55.0, 35.0]), np.log([1.25, 0.8, 0.7]), np.log(1.4), 12.0]
    sp, mu, fa = st.unpack(truth, fixed)
    # Independent of the fit: the multiplier scales the fitted classes only;
    # roadless and local keep their published defaults in every group.
    v = ground.class_income_speeds(sp, mu)
    assert (v[0] == 5.0).all() and (v[5] == 25.0).all()
    assert np.allclose(v[1], 75.0 * mu)
    y = ground.predict_structured(km, sp, mu, fa) + st.end_minutes(truth)
    got = ground.fit_structured(km, y, st, fixed, np.full(n, 1.0 / n))
    assert np.allclose(got, truth, atol=1e-3), (got, truth)
