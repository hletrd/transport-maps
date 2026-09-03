"""Single-source shortest path over the multi-modal graph."""

import h3
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra as _dijkstra

from transport_maps import config
from transport_maps.graph.nodes import NodeIndex


def solve_from(csr: sp.csr_matrix, source: int) -> np.ndarray:
    """Minutes from `source` to every node. Unreachable nodes are inf."""
    return _dijkstra(csgraph=csr, directed=True, indices=source)


def origin_node(idx: NodeIndex, lat: float, lon: float) -> int:
    """Graph node for an origin city centre."""
    cell = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    try:
        return idx.cell_index(cell)
    except KeyError as exc:
        raise ValueError(f"origin ({lat}, {lon}) is not on a land cell") from exc
