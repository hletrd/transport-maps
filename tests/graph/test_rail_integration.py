"""Rail wired into the graph: the boarding cost must not compound."""

import h3
import numpy as np
import polars as pl
import pytest
import scipy.sparse as sp

from transport_maps import config
from transport_maps.graph import build, rail
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources.osm import SCHEMA

CAL = rail.RailCalibration(highspeed_kmh=200.0, conventional_kmh=75.0,
                           detour_factor=1.2, boarding_min=15.0, alighting_min=5.0)

# Three stops on one line, far enough apart to occupy distinct solve cells.
STOPS = [(48.85, 2.35, "A"), (47.00, 3.50, "B"), (45.76, 4.84, "C")]


def _routes():
    return pl.DataFrame(
        [{"route_id": 1, "seq": i, "stop_id": i, "lat": la, "lon": lo,
          "name": nm, "highspeed": False} for i, (la, lo, nm) in enumerate(STOPS)],
        schema=SCHEMA)


def _index():
    keys = [rail.station_key(la, lo) for la, lo, _ in STOPS]
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo, _ in STOPS]
    assert len(set(cells)) == 3, "fixture stops must sit in distinct cells"
    cell_pos = {c: i for i, c in enumerate(cells)}
    station_pos = {k: len(cells) + i for i, k in enumerate(keys)}
    station_cell = {k: cell_pos[c] for k, c in zip(keys, cells)}
    return NodeIndex(cells, [], cell_pos, {}, {}, (),
                     tuple(keys), station_pos, station_cell), keys, cells


def _rail_only_graph(idx):
    rows, cols, data = build._rail_edges(idx, _routes(), CAL)
    return sp.coo_matrix((data, (rows, cols)), shape=(idx.n, idx.n)).tocsr()


def test_boarding_is_charged_once_across_a_multi_stop_ride():
    """Riding A -> B -> C must cost boarding + both rides + alighting.

    Charging boarding per hop is what cell-to-cell rail edges would do, and it
    is why stations are separate nodes at all.
    """
    idx, keys, _ = _index()
    csr = _rail_only_graph(idx)
    d = sp.csgraph.dijkstra(csr, indices=[0])[0]

    rides = rail.ride_edges(_routes(), CAL)["minutes"].sum()
    assert d[2] == pytest.approx(CAL.boarding_min + rides + CAL.alighting_min)
    # Explicitly NOT the per-hop figure.
    assert d[2] < 2 * CAL.boarding_min + rides + CAL.alighting_min


def test_rail_edges_are_traversable_in_both_directions():
    """OSM often models only one direction of a service as a relation."""
    idx, _, _ = _index()
    csr = _rail_only_graph(idx)
    forward = sp.csgraph.dijkstra(csr, indices=[0])[0][2]
    backward = sp.csgraph.dijkstra(csr, indices=[2])[0][0]
    assert forward == pytest.approx(backward)
    assert np.isfinite(forward)


def test_stations_without_a_routes_frame_are_refused():
    """Station nodes with no rail edges would sit unreachable, dragging the
    coverage gate down with no indication of why."""
    idx, _, _ = _index()
    with pytest.raises(ValueError, match="no rail_routes"):
        build.build_graph(idx)
