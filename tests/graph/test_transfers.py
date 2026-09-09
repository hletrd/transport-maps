"""Airport time, split by what it actually depends on.

The previous model lumped check-in, security, boarding, emigration, baggage and
immigration into one "access"/"egress" pair with a domestic and an international
variant, and — because the graph is built before any journey is known — applied
the international variant everywhere. That charged a Frankfurt-Munich hop for a
border it never crosses and an Amsterdam-Milan flight for a passport desk that
does not exist.

Now: processing and disembark are properties of the AIRPORT and stay on the
cell<->airport edges; border control is a property of the ROUTE and is charged
on the flight edge, only when the flight leaves its immigration zone.
"""

import pytest

from transport_maps.graph import air, transfers

SIZES = ("large", "medium", "small")


@pytest.fixture(scope="module")
def cal():
    return air.load_calibration()


# --- immigration zones -------------------------------------------------------

@pytest.mark.parametrize("dep,arr", [("KR", "JP"), ("KR", "US"), ("GB", "FR"), ("US", "MX")])
def test_flights_leaving_the_immigration_zone_cross_a_border(dep, arr):
    assert transfers.crosses_border(dep, arr)


@pytest.mark.parametrize("dep,arr,why", [
    ("DE", "DE", "same country"),
    ("NL", "IT", "both Schengen"),
    ("FR", "ES", "both Schengen"),
    ("IE", "GB", "Common Travel Area"),
])
def test_flights_inside_one_immigration_zone_do_not(dep, arr, why):
    assert not transfers.crosses_border(dep, arr), why


def test_schengen_is_one_zone_but_not_the_whole_world():
    """Guards against a zone table so broad it makes every border vanish."""
    assert transfers.immigration_zone("NL") == transfers.immigration_zone("IT")
    assert transfers.immigration_zone("NL") != transfers.immigration_zone("US")
    assert transfers.immigration_zone("JP") == "JP"


# --- component magnitudes ----------------------------------------------------

def test_processing_exceeds_disembark_at_every_size(cal):
    """Getting onto an aircraft takes longer than getting off one: check-in and
    security have no counterpart on arrival once border control is separated out.
    """
    for size in SIZES:
        assert transfers.processing_min(size, cal) > transfers.disembark_min(size, cal)


@pytest.mark.parametrize("fn", ["processing_min", "disembark_min", "border_min", "connection_min"])
def test_every_component_decreases_with_airport_size(fn, cal):
    """Terminal size is the proxy for queue length, so all four must order the
    same way. A swapped pair of entries in any one table would pass a test that
    only checked large vs small on a single component.
    """
    f = getattr(transfers, fn)
    large, medium, small = (f(s, cal) for s in SIZES)
    assert large > medium > small


def test_components_match_the_calibration_file(cal):
    """Pins the middle tier too: a medium/small swap changes no other assertion."""
    assert transfers.processing_min("large", cal) == 70.0
    assert transfers.processing_min("medium", cal) == 55.0
    assert transfers.disembark_min("large", cal) == 30.0
    assert transfers.disembark_min("medium", cal) == 22.0
    assert transfers.border_min("large", cal) == 45.0
    assert transfers.border_min("medium", cal) == 35.0


def test_border_is_a_real_cost_not_a_rounding_error(cal):
    """If border time were negligible the split would buy nothing; it should be
    a material share of the airport overhead it was carved out of.
    """
    for size in SIZES:
        assert transfers.border_min(size, cal) >= 0.3 * transfers.processing_min(size, cal)

