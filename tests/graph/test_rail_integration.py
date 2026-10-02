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

# Shared with test_rail.py rather than restated. Both files used to build their
# own seven-key row against an eight-column SCHEMA, so `route_name` was null in
# both and adding a column silently widened the hole in two places at once.
from .test_rail import cal, stop

CAL = cal()

# Three stops on one line, far enough apart to occupy distinct solve cells.
STOPS = [(48.85, 2.35, "A"), (47.00, 3.50, "B"), (45.76, 4.84, "C")]


def _routes():
    return pl.DataFrame(
        [stop(1, i, la, lo, nm, "regional", route_name="Line One",
              operator="Test Railways", ref="42")
         for i, (la, lo, nm) in enumerate(STOPS)],
        schema=SCHEMA)


def _index():
    keys = [rail.station_key(la, lo) for la, lo, _ in STOPS]
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo, _ in STOPS]
    assert len(set(cells)) == 3, "fixture stops must sit in distinct cells"
    cell_pos = {c: i for i, c in enumerate(cells)}
    station_pos = {k: len(cells) + i for i, k in enumerate(keys)}
    station_cell = {k: cell_pos[c] for k, c in zip(keys, cells)}
    # By keyword: the refinement fields (base_cells, base_index, fine, _split)
    # sit between `stations` and the station maps, so passed positionally the
    # maps landed in base_cells/base_index and every station lookup failed.
    return NodeIndex(cells, [], cell_pos, {}, {}, (), stations=tuple(keys),
                     _station_pos=station_pos, _station_cell=station_cell), keys, cells


def _rail_only_graph(idx):
    rows, cols, data = build._rail_edges(idx, _routes(), CAL)
    return sp.coo_matrix((data, (rows, cols)), shape=(idx.n, idx.n)).tocsr()


@pytest.mark.needs_inputs
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


@pytest.mark.needs_inputs
def test_boarding_and_alighting_are_charged_at_the_right_END_of_the_journey():
    """The assertion above is symmetric in the two constants and cannot see a swap.

    `boarding_min + rides + alighting_min` is the same number whichever way
    round the two are charged, so a build that taxed 5 minutes to reach the
    platform and 15 to leave the arrival station scored an identical 399.020
    and every rail test stayed green. Asymmetric constants make the swap
    visible: the cost of riding out is boarding, the cost of riding back is
    alighting, and they differ.
    """
    idx, keys, cells = _index()
    asym = rail.RailCalibration(detour_factor=CAL.detour_factor,
                                boarding_min=40.0, alighting_min=1.0,
                                tiers=CAL.tiers)
    rows, cols, data = build._rail_edges(idx, _routes(), asym)
    csr = sp.coo_matrix((data, (rows, cols)), shape=(idx.n, idx.n)).tocsr()

    # A whole journey pays boarding + rides + alighting whichever way round the
    # two constants are charged, so measure the HALF journeys instead: the
    # single edge from a cell to its station, and from a station to its cell.
    station_of = {k: idx._station_pos[k] for k in keys}
    from_cell0 = sp.csgraph.dijkstra(csr, indices=[0])[0]
    assert from_cell0[station_of[keys[0]]] == pytest.approx(asym.boarding_min)

    to_cell2 = sp.csgraph.dijkstra(csr, indices=[station_of[keys[2]]])[0]
    assert to_cell2[2] == pytest.approx(asym.alighting_min)


@pytest.mark.needs_inputs
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
