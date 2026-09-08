"""Ferry crossings as cell-to-cell edges."""

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.graph import build, rail
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources.osm import FERRY_SCHEMA

CAL = rail.FerryCalibration(speed_kmh=35.0, terminal_min=30.0)

# Helsinki and Tallinn: a real 80 km crossing, and comfortably distinct cells.
HEL = (60.15, 24.95)
TLL = (59.44, 24.75)


def _links(rows):
    return pl.DataFrame(rows, schema=FERRY_SCHEMA)


def _link(way_id, a, b, name="ferry"):
    return {"way_id": way_id, "from_lat": a[0], "from_lon": a[1],
            "to_lat": b[0], "to_lon": b[1], "name": name}


def _index(points):
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo in points]
    cells = list(dict.fromkeys(cells))
    return NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())


def test_a_crossing_becomes_a_two_way_edge_with_a_plausible_time():
    idx = _index([HEL, TLL])
    r, c, d = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 2, "a crossing must be traversable both ways"
    assert set(zip(r, c)) == {(0, 1), (1, 0)}
    # ~80 km at 35 km/h plus 30 min terminal: the real sailing is about 2 h.
    assert 100 <= d[0] <= 200
    assert d[0] == pytest.approx(d[1])


def test_a_crossing_inside_one_cell_is_dropped():
    """A self-loop is a zero-length edge Dijkstra could sit on forever."""
    near = (60.15, 24.95), (60.151, 24.951)
    idx = _index([near[0]])
    r, _, _ = build._ferry_edges(idx, _links([_link(1, *near)]), CAL)
    assert len(r) == 0


def test_two_ways_joining_the_same_cells_collapse_to_the_quickest():
    """build_graph refuses duplicate (row, col) pairs, so this must not emit
    them -- and the survivor must be the faster crossing, not the sum."""
    idx = _index([HEL, TLL])
    direct = _link(1, HEL, TLL)
    detour = _link(2, HEL, (59.40, 25.30))     # same cells, longer sail
    r, c, d = build._ferry_edges(idx, _links([direct, detour]), CAL)
    assert len(r) == len(set(zip(r, c))), "emitted a duplicate (row, col) pair"
    solo, _, solo_d = build._ferry_edges(idx, _links([direct]), CAL)
    assert d.min() == pytest.approx(solo_d.min())


def test_crossings_outside_the_plausible_range_are_dropped():
    idx = _index([HEL, TLL, (10.0, 10.0)])
    absurd = _link(1, (60.15, 24.95), (-40.0, -70.0))   # > 4000 km
    r, _, _ = build._ferry_edges(idx, _links([absurd]), CAL)
    assert len(r) == 0


def test_a_crossing_to_a_cell_outside_the_land_mask_is_dropped():
    idx = _index([HEL])                     # Tallinn's cell is absent
    r, _, _ = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 0
