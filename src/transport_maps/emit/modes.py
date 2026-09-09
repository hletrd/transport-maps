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

# Order of the three uint16 channels in the emitted file.
CHANNELS = ("rail", "ferry", "road")
MAX_MINUTES = 65534


def mode_minutes_per_node(idx, minutes: np.ndarray, predecessors: np.ndarray) -> np.ndarray:
    """(n_nodes, 3) array of minutes spent on rail, ferry and road.

    Accumulated down the shortest-path tree in one pass ordered by distance, so
    every node's predecessor is already resolved. The mode of an edge is read
    off the node kinds it joins; the one ambiguous case is cell -> cell, which
    is road when the cells are H3 neighbours and a ferry when they are not,
    since only a crossing can join two cells that do not touch.
    """
    n_cells = idx.n_cells
    n_air = len(idx.airports)
    first_arr = n_cells + n_air
    first_stn = n_cells + 2 * n_air

    acc = np.zeros((len(minutes), 3), dtype=np.float64)
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
            neighbours = h3.grid_disk(idx.cells[prev], 1)
            acc[node][2 if idx.cells[node] in neighbours else 1] += cost
        elif prev_stn or node_stn:
            # Boarding, riding and alighting all count as rail.
            acc[node][0] += cost
        # Everything else is air or airport time, already itemised from the
        # routes file, so it is deliberately not counted here.

    return acc


def write_modes(idx, minutes: np.ndarray, predecessors: np.ndarray, out: Path) -> None:
    """Three uint16 channels per hover cell, in `hover_cells` order.

    Taken from the same res-5 child the hover time came from, so the breakdown
    describes the journey the number refers to rather than a different one.
    """
    parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})
    position = {cell: i for i, cell in enumerate(parents)}

    acc = mode_minutes_per_node(idx, minutes, predecessors)
    best = np.full(len(parents), np.inf)
    picked = np.zeros((len(parents), 3), dtype=np.float64)
    for pos, cell in enumerate(idx.cells):
        p = position[h3.cell_to_parent(cell, config.HOVER_RES)]
        if minutes[pos] < best[p]:
            best[p] = minutes[pos]
            picked[p] = acc[pos]

    encoded = np.clip(np.nan_to_num(picked, posinf=0.0), 0, MAX_MINUTES).astype("<u2")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded.tobytes())
