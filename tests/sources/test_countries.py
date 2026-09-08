"""Closed land borders must actually cut the ground graph."""

import h3
import numpy as np
import pytest
import scipy.sparse as sp

from transport_maps import config
from transport_maps.graph import ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import countries


def test_known_places_resolve_to_their_country():
    pts = [(37.5665, 126.978, "KOR"), (39.03, 125.75, "PRK"),
           (35.68, 139.69, "JPN"), (40.18, 44.51, "ARM")]
    cells = [h3.latlng_to_cell(la, lo, 5) for la, lo, _ in pts]
    got = countries.cell_country(cells)
    assert list(got) == [c for _, _, c in pts]


@pytest.mark.parametrize("a,b,closed", [
    ("KOR", "PRK", True), ("ARM", "AZE", True), ("DZA", "MAR", True),
    ("KOR", "JPN", False), ("FRA", "DEU", False),
    ("KOR", "KOR", False), ("", "PRK", False),
])
def test_closed_border_table(a, b, closed):
    assert countries.is_closed(a, b) is closed


def test_the_inter_korean_border_is_not_traversable_on_the_ground():
    """A chain of cells across the DMZ must not connect end to end.

    Without the cut, Seoul is reachable overland from Vladivostok and the whole
    peninsula reads as one road network.
    """
    # A north-south line of cells spanning the border near the eastern coast.
    lats = np.arange(37.6, 39.2, 0.05)
    cells = list(dict.fromkeys(h3.latlng_to_cell(la, 127.6, config.SOLVE_RES)
                               for la in lats))
    idx = NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())

    codes = countries.cell_country(cells)
    assert "KOR" in codes and "PRK" in codes, "fixture does not span the border"

    r, c, d = ground.hex_edges(idx)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
    south = int(np.where(codes == "KOR")[0][0])
    north = int(np.where(codes == "PRK")[0][-1])
    assert not np.isfinite(sp.csgraph.dijkstra(csr, indices=[south])[0][north]), \
        "ground route crosses the sealed inter-Korean border"
