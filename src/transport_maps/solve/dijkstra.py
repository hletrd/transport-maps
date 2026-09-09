"""Single-source shortest path over the multi-modal graph."""

import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra as _dijkstra

from transport_maps.graph.nodes import NodeIndex


def solve_from(csr: sp.csr_matrix, source: int, with_predecessors: bool = False):
    """Minutes from `source` to every node. Unreachable nodes are inf.

    Returns `(dist, pred)` when `with_predecessors` is set, else `dist` alone.
    """
    if with_predecessors:
        return _dijkstra(
            csgraph=csr, directed=True, indices=source, return_predecessors=True
        )
    return _dijkstra(csgraph=csr, directed=True, indices=source)


def origin_node(idx: NodeIndex, lat: float, lon: float) -> int:
    """Graph node for an origin city centre."""
    cell = idx.cell_at(lat, lon)
    try:
        return idx.cell_index(cell)
    except KeyError as exc:
        raise ValueError(f"origin ({lat}, {lon}) is not on a land cell") from exc
