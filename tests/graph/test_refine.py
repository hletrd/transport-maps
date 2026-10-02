import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.graph import refine


def test_dense_where_roads_are_good_or_a_city_is_near():
    cls = np.array([0, 1, 2, 3, 4, 5, 0])
    urban = np.array([False, False, False, False, False, False, True])
    assert refine.dense_mask(cls, urban).tolist() == [False, True, True, True, False, False, True]


def test_split_cells_become_their_seven_children_and_keep_their_base_index():
    base = sorted(h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES), 1))
    split = np.zeros(len(base), dtype=bool)
    split[2] = True
    cells, base_index, fine = refine.refine(base, split)
    assert len(cells) == len(base) - 1 + 7
    assert not fine[: len(base) - 1].any() and fine[len(base) - 1:].all()
    kids = [c for c, f in zip(cells, fine) if f]
    assert all(h3.get_resolution(c) == config.FINE_RES for c in kids)
    assert all(h3.cell_to_parent(c, config.SOLVE_RES) == base[2] for c in kids)
    assert (base_index[fine] == 2).all()
    # unsplit cells map to themselves
    for c, i in zip(cells[: len(base) - 1], base_index[: len(base) - 1]):
        assert base[i] == c


def test_base_values_carry_down_to_children():
    """Every child of a split cell carries its parent's value -- not zero.

    The old fixture split cell 0, whose value was 0, so carry-down and a
    zero-fill of the children were indistinguishable and the test asserted
    the zero.
    """
    base = sorted(h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES), 1))
    split = np.zeros(len(base), dtype=bool); split[2] = True
    cells, base_index, fine = refine.refine(base, split)

    class Idx:
        pass
    idx = Idx(); idx.base_index = base_index
    values = np.arange(len(base)) * 10 + 7
    out = refine.expand(values, idx)
    assert len(out) == len(cells)
    assert out[fine].size == 7 and (out[fine] == values[2]).all(), "children did not inherit the parent's value"
    for i, (c, f) in enumerate(zip(cells, fine)):
        if not f:
            assert out[i] == values[base.index(c)]


def test_ground_adjacency_is_judged_the_way_hex_edges_joins_cells():
    """A fine cell touches the unsplit base cell beyond its ring, and nothing
    further: not the base cell on the far side of its parent (which a
    base-parent comparison called adjacent), and not a sibling it does not
    touch."""
    base = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    neighbour = h3.grid_ring(base, 1)[0]
    kids = h3.cell_to_children(base, config.FINE_RES)

    def km(k):
        return h3.great_circle_distance(h3.cell_to_latlng(k), h3.cell_to_latlng(neighbour), unit="km")
    edge_kid, far_kid = min(kids, key=km), max(kids, key=km)
    assert refine.ground_adjacent(edge_kid, neighbour)
    assert refine.ground_adjacent(neighbour, edge_kid)
    assert not refine.ground_adjacent(far_kid, neighbour), "the far child does not touch the neighbour"
    assert not refine.ground_adjacent(edge_kid, h3.grid_ring(base, 3)[0])
    # Same resolution: neighbours and only neighbours.
    centre_kid = h3.cell_to_center_child(base, config.FINE_RES)
    assert refine.ground_adjacent(centre_kid, edge_kid)
    assert not refine.ground_adjacent(edge_kid, far_kid), "opposite children of one parent do not touch"
    assert refine.ground_adjacent(base, neighbour)
    assert not refine.ground_adjacent(base, h3.grid_ring(base, 2)[0])


def _toward(cell: str, target: str, frac: float) -> tuple[float, float]:
    """A point `frac` of the way from cell's centre toward target's centre."""
    (la, lo), (ta, to) = h3.cell_to_latlng(cell), h3.cell_to_latlng(target)
    return la + frac * (ta - la), lo + frac * (to - lo)


def test_an_airport_off_the_mask_snaps_to_the_nearest_land_cell_within_two_rings():
    from transport_maps.graph.nodes import _nearest_land
    centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    ring2 = h3.grid_ring(centre, 2)
    land = {c: i for i, c in enumerate(ring2)}          # only ring 2 is "land"
    # Off-centre toward one ring-2 cell: that exact cell must win, not the
    # first indexed one the ring walk happens to visit.
    la, lo = _toward(centre, ring2[7], 0.4)
    found = _nearest_land(centre, land, la, lo)
    assert found is not None
    pos, km = found
    assert ring2[pos] == ring2[7], "did not pick the nearest ring-2 cell"
    assert 0 < km < 15
    # nothing within two rings -> None
    assert _nearest_land(centre, {h3.grid_ring(centre, 3)[0]: 0}, la, lo) is None


def test_the_snap_sees_a_split_neighbour_through_its_fine_children():
    """A dense coastal cell is in the index only as its res-7 children, so a
    lookup by its res-6 id found nothing and the search walked past it to a
    farther unsplit cell (or dropped the airport): Kitakyushu, Bodø, Ushuaia.
    """
    from transport_maps.graph.nodes import _nearest_land
    centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    ring1, ring2 = h3.grid_ring(centre, 1), h3.grid_ring(centre, 2)
    dense = ring1[0]
    kids = h3.cell_to_children(dense, config.FINE_RES)
    far = ring2[0]
    land = {k: i for i, k in enumerate(kids)}
    land[far] = len(kids)
    la, lo = _toward(centre, dense, 0.3)
    found = _nearest_land(centre, land, la, lo, split={dense})
    assert found is not None
    pos, km = found
    assert pos < len(kids), "snapped to the far unsplit cell instead of the adjacent dense cell"
    expected = min(kids, key=lambda k: h3.great_circle_distance((la, lo), h3.cell_to_latlng(k), unit="km"))
    assert kids[pos] == expected, "not the nearest child"


def _seven_cell_index():
    centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    cells = [centre, *h3.grid_ring(centre, 1)]
    return cells, {c: i for i, c in enumerate(cells)}


def test_airports_are_placed_snapped_or_dropped_and_the_snapped_share_is_bounded(monkeypatch):
    import polars as pl

    from transport_maps.graph import nodes
    cells, cell_pos = _seven_cell_index()
    centre_lat, centre_lon = h3.cell_to_latlng(cells[0])
    # one airport on the mask, one a ring-2 cell off it (snaps), one mid-ocean (dropped)
    off = h3.grid_ring(cells[0], 2)[0]
    apts = pl.DataFrame({"iata": ["AAA", "BBB", "CCC"],
                         "lat": [centre_lat, h3.cell_to_latlng(off)[0], 0.0],
                         "lon": [centre_lon, h3.cell_to_latlng(off)[1], -160.0]})
    monkeypatch.setattr(nodes, "MAX_DROPPED_AIRPORT_FRACTION", 1.0)
    monkeypatch.setattr(nodes, "MAX_SNAPPED_AIRPORT_FRACTION", 1.0)
    codes, airport_cell, dropped = nodes._place_airports(apts, cell_pos, frozenset())
    assert codes == ["AAA", "BBB"] and dropped == ["CCC"]
    assert airport_cell["AAA"] == 0 and airport_cell["BBB"] in range(1, 7)

    # The snapped bound is a gate: a mask that lost its coast snaps everything.
    monkeypatch.setattr(nodes, "MAX_SNAPPED_AIRPORT_FRACTION", 0.05)
    with pytest.raises(RuntimeError, match="lost its coast"):
        nodes._place_airports(apts, cell_pos, frozenset())


def test_a_cell_a_strait_runs_through_is_split_whatever_its_roads():
    """Only dense cells used to be split, so a straddler in open country
    joined both shores whole (graph/landmass). Antarctica is one landmass to
    the severing rule and is never split for it.

    Mutations performed and reverted, each -> red: `len(p) > 0` (every land
    cell split); the Antarctica clause dropped.
    """
    ANT = -1
    parts = [(3,), (3, 7), (), (ANT, 4), (5, 6, 9)]
    assert refine.straddler_mask(parts, ANT).tolist() == [False, True, False, False, True]
