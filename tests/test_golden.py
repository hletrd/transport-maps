"""Door-to-door times for known city pairs, asserted within tolerance.

Loose in Phase A, tightened (B3, 2026-10-02) to the shipped build's values
plus a stated tolerance: Seoul -> Tokyo 314 min and Seoul -> London 904 min,
measured on the graph that produced the 1,464-origin dist/. A band of +-15%
absorbs a recalibration or a route-network refresh; a move past it is a model
change and should be measured, not absorbed. Update the tolerances, never the
expectations, as the model improves.
"""

import pytest

from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra

# Builds the full node index from the cached universe: minutes, real caches.
pytestmark = pytest.mark.integration

SEOUL = (37.5665, 126.9780)
TOKYO = (35.6762, 139.6503)
LONDON = (51.5072, -0.1276)


@pytest.fixture(scope="module")
def solved():
    idx = nodes.build_index()
    csr = build.build_graph(idx)
    minutes = dijkstra.solve_from(csr, dijkstra.origin_node(idx, *SEOUL))
    return idx, minutes


def _minutes_at(idx, minutes, latlon) -> float:
    # The index resolves base-versus-fine: Tokyo and London sit in split cells.
    return float(minutes[idx.cell_index(idx.cell_at(*latlon))])


# Shipped values (2026-10-02) and the tolerance around them; see the docstring.
TOKYO_MIN, LONDON_MIN, TOLERANCE = 314, 904, 0.15


def _near(value, shipped):
    return shipped * (1 - TOLERANCE) < value < shipped * (1 + TOLERANCE)


def test_seoul_to_tokyo_is_a_half_day_or_less(solved):
    idx, minutes = solved
    assert 120 < _minutes_at(idx, minutes, TOKYO) < 720


def test_seoul_to_tokyo_is_near_the_shipped_value(solved):
    idx, minutes = solved
    assert _near(_minutes_at(idx, minutes, TOKYO), TOKYO_MIN)


def test_seoul_to_london_is_near_the_shipped_value(solved):
    idx, minutes = solved
    assert _near(_minutes_at(idx, minutes, LONDON), LONDON_MIN)


def test_seoul_to_london_is_longer_than_seoul_to_tokyo(solved):
    idx, minutes = solved
    assert _minutes_at(idx, minutes, LONDON) > _minutes_at(idx, minutes, TOKYO)


def test_seoul_to_london_is_under_two_days(solved):
    idx, minutes = solved
    assert _minutes_at(idx, minutes, LONDON) < 2880


def test_the_vast_majority_of_land_is_reachable(solved):
    """Measured the way the build gates it (TE-19): Antarctica, charted but
    never served, is outside the denominator. The raw fraction counted it, so
    this test and the gate disagreed about the same solve (96.9% raw against
    99.5% gated, 2026-10-02)."""
    from transport_maps import validate

    idx, minutes = solved
    assert validate.check_coverage(minutes, idx) > validate.MIN_COVERAGE
