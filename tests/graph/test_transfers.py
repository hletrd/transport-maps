import pytest

from transport_maps.graph import air, transfers


@pytest.fixture(scope="module")
def cal():
    return air.load_calibration()


def test_international_access_exceeds_domestic(cal):
    assert transfers.access_min("large", True, cal) > transfers.access_min("large", False, cal)


def test_international_egress_exceeds_domestic_egress(cal):
    # Pins the domestic/international direction on egress independently of
    # access -- a bug that swaps the two keys only inside egress_min would
    # slip past test_egress_is_shorter_than_access below, since a swapped
    # egress value can still happen to be smaller than access.
    assert transfers.egress_min("large", True, cal) > transfers.egress_min("large", False, cal)


def test_large_hubs_have_longer_connections_than_small_airports(cal):
    assert transfers.connection_min("large", cal) > transfers.connection_min("small", cal)


def test_access_min_size_ordering_domestic(cal):
    # A bigger airport takes longer to get through -- large > medium > small.
    # This single relational test catches a medium/small transposition in
    # either direction, on top of the large/small check connection_min
    # already had.
    large = transfers.access_min("large", False, cal)
    medium = transfers.access_min("medium", False, cal)
    small = transfers.access_min("small", False, cal)
    assert large > medium > small


def test_access_min_size_ordering_international(cal):
    large = transfers.access_min("large", True, cal)
    medium = transfers.access_min("medium", True, cal)
    small = transfers.access_min("small", True, cal)
    assert large > medium > small


def test_egress_min_size_ordering_domestic(cal):
    large = transfers.egress_min("large", False, cal)
    medium = transfers.egress_min("medium", False, cal)
    small = transfers.egress_min("small", False, cal)
    assert large > medium > small


def test_egress_min_size_ordering_international(cal):
    large = transfers.egress_min("large", True, cal)
    medium = transfers.egress_min("medium", True, cal)
    small = transfers.egress_min("small", True, cal)
    assert large > medium > small


def test_egress_is_shorter_than_access(cal):
    # Leaving an airport is faster than entering one: no check-in, no security.
    assert transfers.egress_min("large", True, cal) < transfers.access_min("large", True, cal)


def test_access_min_matches_calibrated_values(cal):
    # Pins exact values so a transposition between the domestic/international
    # tables (or between access_min and egress_min) that happens to preserve
    # the relational asserts above is still caught. The medium tier is pinned
    # too, in both variants -- otherwise it is never referenced by value and a
    # medium/small swap could pass every other test in this file.
    assert transfers.access_min("large", False, cal) == pytest.approx(70.0)
    assert transfers.access_min("medium", False, cal) == pytest.approx(55.0)
    assert transfers.access_min("large", True, cal) == pytest.approx(100.0)
    assert transfers.access_min("medium", True, cal) == pytest.approx(80.0)


def test_egress_min_matches_calibrated_values(cal):
    assert transfers.egress_min("large", False, cal) == pytest.approx(30.0)
    assert transfers.egress_min("medium", False, cal) == pytest.approx(22.0)
    assert transfers.egress_min("large", True, cal) == pytest.approx(55.0)
    assert transfers.egress_min("medium", True, cal) == pytest.approx(45.0)


def test_connection_min_matches_calibrated_values(cal):
    assert transfers.connection_min("large", cal) == pytest.approx(75.0)
    assert transfers.connection_min("small", cal) == pytest.approx(35.0)
