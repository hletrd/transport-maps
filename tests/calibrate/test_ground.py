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
