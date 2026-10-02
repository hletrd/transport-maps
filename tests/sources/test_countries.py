"""Closed land borders must actually cut the ground graph."""

from itertools import pairwise

import h3
import numpy as np
import pytest
import scipy.sparse as sp

from transport_maps import config
from transport_maps.graph import ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import countries


@pytest.mark.needs_inputs
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


def _chain(lat_south: float, lat_north: float, lon: float) -> list[str]:
    """Every consecutive pair adjacent, or the cut is untestable.

    Sampling a line of latitudes at res 6 skipped cells (four gaps on the
    eastern chain), so north was unreachable from south whether or not the
    border was cut and the test stayed green with the cut deleted.
    """
    south = h3.latlng_to_cell(lat_south, lon, config.SOLVE_RES)
    north = h3.latlng_to_cell(lat_north, lon, config.SOLVE_RES)
    cells = h3.grid_path_cells(south, north)
    assert all(h3.are_neighbor_cells(a, b) for a, b in pairwise(cells)), \
        "fixture chain has a gap; the border cut cannot be exercised"
    return cells


def _cut_end_to_end(cells: list[str]) -> None:
    idx = NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())
    codes = countries.cell_country(cells)
    assert "KOR" in codes and "PRK" in codes, "fixture does not span the border"
    assert countries.UNKNOWN not in codes, "a blank cell survives on the chain"
    r, c, d = ground.hex_edges(idx)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
    south = int(np.where(codes == "KOR")[0][0])
    north = int(np.where(codes == "PRK")[0][-1])
    assert not np.isfinite(sp.csgraph.dijkstra(csr, indices=[south])[0][north]), \
        "ground route crosses the sealed inter-Korean border"


@pytest.mark.needs_inputs
def test_the_inter_korean_border_is_not_traversable_on_the_ground():
    """A chain of cells across the DMZ must not connect end to end.

    Without the cut, Seoul is reachable overland from Vladivostok and the whole
    peninsula reads as one road network.
    """
    # A north-south line of cells spanning the border near the eastern coast.
    _cut_end_to_end(_chain(37.6, 39.2, 127.6))


@pytest.mark.needs_inputs
def test_a_land_border_between_immigration_zones_costs_a_crossing():
    """Singapore to Johor Bahru is a fifteen-minute drive plus a passport desk.

    Air routes already paid border_min when leaving an immigration zone; ground
    edges paid nothing, which made the causeway free.
    """
    sg = h3.latlng_to_cell(1.44, 103.78, config.SOLVE_RES)      # Woodlands
    # The Malaysian cell across the strait is found by country rather than by
    # a coordinate: a Johor Bahru point one cell away at res 5 is two away at
    # res 6, and only an adjacent pair has a ground edge to charge.
    ring = h3.grid_ring(sg, 1)
    codes = countries.cell_country([sg, *ring])
    assert codes[0] == "SGP", codes
    jb = next(c for c, code in zip(ring, codes[1:]) if code == "MYS")
    idx = NodeIndex([sg, jb], [], {sg: 0, jb: 1}, {}, {}, ())
    r, c, d = ground.hex_edges(idx)
    edge = {(int(a), int(b)): float(m) for a, b, m in zip(r, c, d)}
    dist_only = ground.haversine_km(
        np.array([h3.cell_to_latlng(sg)]), np.array([h3.cell_to_latlng(jb)]))[0]
    assert edge[(0, 1)] > dist_only / 120 * 60 + 30, \
        "crossing SG -> MY cost no more than the drive itself"


@pytest.mark.needs_inputs
def test_a_schengen_border_costs_nothing_extra():
    """Two cells in different Schengen states share an immigration zone, so the
    edge between them is the drive and nothing more. The pair is found by
    country, not by a coordinate: the old fixture guarded its only assertion
    with an `if` that a country-table change would have turned into a silent
    pass."""
    corner = h3.latlng_to_cell(47.59, 7.59, config.SOLVE_RES)      # Basel: DE/CH/FR meet
    ring = h3.grid_ring(corner, 1)
    codes = countries.cell_country([corner, *ring])
    assert codes[0] in ("DEU", "FRA", "CHE"), codes[0]
    other = next((c for c, code in zip(ring, codes[1:])
                  if code in ("DEU", "FRA", "CHE") and code != codes[0]), None)
    assert other is not None, f"no neighbouring Schengen state found around {codes[0]}"
    idx = NodeIndex([corner, other], [], {corner: 0, other: 1}, {}, {}, ())
    r, c, d = ground.hex_edges(idx)
    dist = ground.haversine_km(
        np.array([h3.cell_to_latlng(corner)]), np.array([h3.cell_to_latlng(other)]))[0]
    assert d.max() < dist / 20 * 60 + 5, "a Schengen-internal edge was charged a crossing"


@pytest.mark.integration
def test_no_land_cell_is_left_without_a_country():
    """A blank cell is a bridge across every closed border.

    Kaesong was reachable from Seoul in 2.5 h by stepping onto a blank
    Han-estuary cell and off it into the North; the KOR/PRK cut never fired
    because neither KOR->'' nor ''->PRK is a closed pair.
    """
    from transport_maps.sources import landmask
    cells = landmask.land_cells(config.SOLVE_RES)
    codes = countries.cell_country(cells)
    blank = int((codes == countries.UNKNOWN).sum())
    assert blank == 0, f"{blank} cells still have no country"


@pytest.mark.needs_inputs
def test_the_western_dmz_is_cut_too():
    """The first DMZ test ran at longitude 127.6; the bridge was at 126.3."""
    _cut_end_to_end(_chain(37.5, 38.3, 126.45))
