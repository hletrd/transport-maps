"""Single-source shortest path over the multi-modal graph."""

import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra as _dijkstra

from transport_maps.graph.nodes import NodeIndex, _nearest_land


def solve_from(csr: sp.csr_matrix, source: int, with_predecessors: bool = False):
    """Minutes from `source` to every node. Unreachable nodes are inf.

    Returns `(dist, pred)` when `with_predecessors` is set, else `dist` alone.
    """
    if with_predecessors:
        return _dijkstra(
            csgraph=csr, directed=True, indices=source, return_predecessors=True
        )
    return _dijkstra(csgraph=csr, directed=True, indices=source)


def snap_origin(idx: NodeIndex, lat: float, lon: float) -> tuple[int, float]:
    """Graph node for an origin city centre, and how far the snap moved it.

    Returns `(position, km)`. `km` is 0.0 when the coordinate's own cell is
    indexed, and the great-circle distance to the chosen cell's centre when it
    is not. Raises `ValueError` when no land cell lies within two rings.

    Split out from `origin_node` so the build's pre-flight
    (`cli._preflight_origins`) can report the distance without reimplementing
    the search. A second copy of the two-ring walk would be free to disagree
    with the one the solver actually uses, which is the failure the pre-flight
    exists to catch -- so there is one implementation and both callers reach
    it.
    """
    cell = idx.cell_at(lat, lon)
    pos = idx.try_cell_index(cell)
    if pos is not None:
        return pos, 0.0
    found = _nearest_land(cell, idx._cell_pos, lat, lon, idx._split)
    if found is not None:
        return found
    raise ValueError(
        f"origin ({lat}, {lon}) is not on a land cell, and no land cell lies "
        "within two rings of it"
    )


def origin_node(idx: NodeIndex, lat: float, lon: float) -> int:
    """Graph node for an origin city centre, snapped to land if it has to be.

    A city centre is on land by definition, but the coordinate in
    `data/origins.toml` is a gazetteer point and the land mask is a 1:10m
    outline, so the two disagree on any shore the outline cuts inside. Kota
    Kinabalu is the case that proved it: 5.9749, 116.0724 lands on res-6 cell
    `8668156e7ffffff`, which is absent from the mask, with three land
    neighbours in ring 1 and the nearest 4.2 km east.

    Before this, that raised a bare `ValueError`. `GateFailure` is a
    `RuntimeError` and `cli.py` catches only `GateFailure`, so a single bad
    coordinate killed a whole multi-day build with a traceback and no slug --
    and it did so at origin 970 of 1,464, 26 hours in. Airports have always
    had this snap (`_place_airports` is `_nearest_land`'s only other caller);
    origins had nothing.

    The snap is the same two-ring search airports get, so it reaches about
    13 km from a res-6 cell and compares every candidate by distance rather
    than taking the first found. Beyond that range the coordinate is wrong
    rather than merely imprecise, and it still raises -- but `cli.py` now
    turns that into a named per-origin failure.
    """
    return snap_origin(idx, lat, lon)[0]
