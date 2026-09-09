"""Door-to-door times for known city pairs, asserted within tolerance.

These are deliberately loose in Phase A (air plus uniform ground) and tighten as
real modes land. Update the tolerances, never the expectations, as the model improves.
"""

import numpy as np
import pytest

from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra

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


def test_seoul_to_tokyo_is_a_half_day_or_less(solved):
    idx, minutes = solved
    assert 120 < _minutes_at(idx, minutes, TOKYO) < 720


def test_seoul_to_london_is_longer_than_seoul_to_tokyo(solved):
    idx, minutes = solved
    assert _minutes_at(idx, minutes, LONDON) > _minutes_at(idx, minutes, TOKYO)


def test_seoul_to_london_is_under_two_days(solved):
    idx, minutes = solved
    assert _minutes_at(idx, minutes, LONDON) < 2880


def test_the_vast_majority_of_land_is_reachable(solved):
    idx, minutes = solved
    reachable = np.isfinite(minutes[: idx.n_cells]).mean()
    assert reachable > 0.90
