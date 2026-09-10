"""Which airport each place was reached through, so the page can show the legs.

The time array answers "how long"; this answers "by what route". Shipping the
full predecessor chain per cell would be tens of megabytes, but one airport
ordinal per hover cell is 181,480 bytes (uint16 x 90,740 hover cells) and is enough: the frontend walks that
airport's `prev` chain in the per-origin routes JSON to recover the whole
sequence of flights and connections.
"""

from pathlib import Path

import h3
import numpy as np

from transport_maps import _io, config

# No airport was involved -- the journey was entirely overland.
NO_AIRPORT = 0xFFFF


def arrival_airport_per_node(idx, minutes: np.ndarray, predecessors: np.ndarray) -> np.ndarray:
    """For every node, the arrival-airport node it was last reached through.

    Computed in one pass over nodes sorted by distance. A node's predecessor is
    always strictly nearer, so it has already been assigned when the node is
    visited; walking each cell's chain back individually would instead be
    quadratic on long overland tails.
    """
    n = len(minutes)
    last = np.full(n, -1, dtype=np.int64)

    first_arrival = idx.n_cells + len(idx.airports)
    last_arrival = first_arrival + len(idx.airports)

    finite = np.isfinite(minutes)
    for node in np.argsort(np.where(finite, minutes, np.inf), kind="stable"):
        node = int(node)
        if not finite[node]:
            break
        if first_arrival <= node < last_arrival:
            last[node] = node
            continue
        prev = int(predecessors[node])
        if prev >= 0:
            last[node] = last[prev]
    return last


def write_itinerary(idx, minutes: np.ndarray, predecessors: np.ndarray, out: Path) -> None:
    """One uint16 airport ordinal per hover cell, in `hover_cells` order.

    The ordinal identifies the SAME solver cell the hover time came from
    (hover._representative_children: the centre child at SOLVE_RES, or the
    fastest child where the centre is water); naming the airport of a
    different child would caption the number with a route that did not
    produce it.
    """
    parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})

    last = arrival_airport_per_node(idx, minutes, predecessors)
    first_arrival = idx.n_cells + len(idx.airports)

    from .hover import _representative_children

    chosen = np.full(len(parents), NO_AIRPORT, dtype=np.int64)
    for p, pos in _representative_children(idx, parents, minutes[: idx.n_cells]).items():
        node = last[pos]
        chosen[p] = NO_AIRPORT if node < 0 else node - first_arrival

    _io.write_bytes(out, chosen.astype("<u2").tobytes())
