"""How the surface part of each journey was actually travelled.

"Surface transport, 5 h" is not a useful thing to tell someone. Rail, road and
ferry differ enormously in what they imply, and across most of the map the
surface leg is a large share of the total -- a median of 1.2 to 1.7 hours even
in Japan, Europe and the United States, and far more in remote country.

Shipping the stations themselves would cost about 1.6 MB per origin (27,843 of
the 57,286 stations lie on some shortest path from Paris). Three minute-totals
per cell cost 6 bytes, and answer the question people actually ask.
"""

from pathlib import Path

import h3
import numpy as np

from transport_maps import config
from transport_maps.graph.refine import ground_adjacent

# Order of the uint16 channels in the emitted file. Road is split by grade
# because "road" covers both a motorway and a dirt track, which is exactly the
# distinction a traveller cares about.
CHANNELS = ("rail", "ferry", "highway", "major road", "minor road", "track")
# GRIP4 class -> channel. 0 roadless, 1 highway, 2 primary, 3 secondary,
# 4 tertiary, 5 local.
ROAD_CHANNEL = {0: 5, 1: 2, 2: 3, 3: 3, 4: 4, 5: 4}
MAX_MINUTES = 65534


def mode_minutes_per_node(idx, minutes: np.ndarray, predecessors: np.ndarray,
                          cell_class: np.ndarray | None = None) -> np.ndarray:
    """(n_nodes, len(CHANNELS)) array of minutes spent in each surface mode.

    Accumulated down the shortest-path tree in one pass ordered by distance, so
    every node's predecessor is already resolved. The mode of an edge is read
    off the node kinds it joins; the one ambiguous case is cell -> cell, which
    is road when the ground network joins the cells (refine.ground_adjacent,
    the same test graph/build uses to drop a ferry that would duplicate a
    ground edge) and a ferry when it does not, since only a crossing can join
    two cells the ground network keeps apart.
    """
    n_cells = idx.n_cells
    n_air = len(idx.airports)
    first_stn = n_cells + 2 * n_air

    if cell_class is None:
        from ..sources import roads

        cell_class = roads.cell_class(idx.cells)
    acc = np.zeros((len(minutes), len(CHANNELS)), dtype=np.float64)
    finite = np.isfinite(minutes)
    order = np.argsort(np.where(finite, minutes, np.inf), kind="stable")

    for node in order:
        node = int(node)
        if not finite[node]:
            break
        prev = int(predecessors[node])
        if prev < 0:
            continue
        acc[node] = acc[prev]
        cost = minutes[node] - minutes[prev]

        prev_cell, node_cell = prev < n_cells, node < n_cells
        prev_stn, node_stn = prev >= first_stn, node >= first_stn

        if prev_cell and node_cell:
            if ground_adjacent(idx.cells[prev], idx.cells[node]):
                acc[node][ROAD_CHANNEL[int(cell_class[node])]] += cost
            else:
                acc[node][1] += cost          # only a crossing joins distant cells
        elif prev_stn or node_stn:
            # Boarding, riding and alighting all count as rail.
            acc[node][0] += cost
        # Everything else is air or airport time, already itemised from the
        # routes file, so it is deliberately not counted here.

    return acc


def write_modes(idx, minutes: np.ndarray, predecessors: np.ndarray, out: Path,
                cell_class: np.ndarray | None = None) -> None:
    """One uint16 channel per mode per hover cell, in `hover_cells` order.

    Taken from the same res-5 child the hover time came from, so the breakdown
    describes the journey the number refers to rather than a different one.
    """
    parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})

    acc = mode_minutes_per_node(idx, minutes, predecessors, cell_class=cell_class)
    from .hover import _representative_children

    picked = np.zeros((len(parents), len(CHANNELS)), dtype=np.float64)
    for p, pos in _representative_children(idx, parents, minutes[: idx.n_cells]).items():
        picked[p] = acc[pos]

    encoded = np.clip(np.nan_to_num(picked, posinf=0.0), 0, MAX_MINUTES).astype("<u2")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded.tobytes())
