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
from transport_maps.emit import _tree
from transport_maps.graph.layout import layout_of

# No airport was involved -- the journey was entirely overland.
NO_AIRPORT = 0xFFFF


def arrival_airport_per_node(idx, minutes: np.ndarray, predecessors: np.ndarray) -> np.ndarray:
    """For every node, the arrival-airport node it was last reached through:
    the nearest arrival node on its path back to the origin, itself included;
    -1 for a journey with none and for a node not reached. (Walking each
    cell's chain back on its own would be quadratic on long overland tails.)
    """
    # Arrival nodes of BOTH airport layers (graph/layout.py): a journey from
    # abroad lands on the international one, and it is still that airport.
    # Whole-array pointer doubling (emit/_tree) in place of the node-by-node
    # walk in distance order, which was ~11 s of an origin; same answer.
    mark = layout_of(idx).is_arrival(np.arange(len(minutes)))
    return _tree.nearest_marked_ancestor(mark, predecessors, np.isfinite(minutes))


def write_itinerary(idx, minutes: np.ndarray, predecessors: np.ndarray, out: Path, *,
                    parents: list[str] | None = None, rep: dict[int, int] | None = None,
                    last: np.ndarray | None = None) -> None:
    """One uint16 airport ordinal per hover cell, in `hover_cells` order.

    The ordinal identifies the SAME solver cell the hover time came from
    (hover._representative_children: the centre child at SOLVE_RES, or the
    fastest child where the centre is water); naming the airport of a
    different child would caption the number with a route that did not
    produce it.
    """
    if parents is None:
        parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})

    if last is None:
        last = arrival_airport_per_node(idx, minutes, predecessors)
    ordinal = layout_of(idx).arrival_ordinal

    from .hover import _representative_children

    chosen = np.full(len(parents), NO_AIRPORT, dtype=np.int64)
    if rep is None:
        rep = _representative_children(idx, parents, minutes[: idx.n_cells])
    for p, pos in rep.items():
        node = last[pos]
        chosen[p] = NO_AIRPORT if node < 0 else ordinal(node)

    _io.write_bytes(out, chosen.astype("<u2").tobytes())
