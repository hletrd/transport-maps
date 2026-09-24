"""Where the fine reading and the coarse route disagree, the route the fine cell took.

The page prints the res-6 reading under the pointer but builds the route panel
-- which airport, the legs, the surface modes -- from arrays kept per res-4
hover cell (itinerary.py, modes.py), taken from ONE representative child. A
res-4 cell is ~22 km across, and where two places inside it travel differently
the panel describes the wrong one. The owner's case: Saipan and Tinian share a
hover cell whose representative is on Saipan, so at Tinian the page printed the
right total, 9 h 34, over "Fly ICN -> SPN ... Onward from SPN ... by highway".

This ships, per origin, the res-6 cells whose own arrival airport differs from
their hover representative's: 283,096 of 4,091,715 from Seoul (6.9%), almost
all at the boundary between two airports' catchments, 1,454 where one flies and
the other does not. Each entry is the reading-tier slot, the airport and the
six mode totals -- 18 bytes, ~5 MB raw per origin.

Format, little-endian, three arrays back to back, sorted by slot so the page
binary-searches it: n uint32 slots, n uint16 airport ordinals (NO_AIRPORT for
none), n x len(CHANNELS) uint16 minutes. n = byteLength / ENTRY_BYTES.
"""

from pathlib import Path

import numpy as np

from transport_maps import _io

from .itinerary import NO_AIRPORT
from .modes import CHANNELS, MAX_MINUTES

ENTRY_BYTES = 4 + 2 + 2 * len(CHANNELS)


def override_entries(idx, last: np.ndarray, acc: np.ndarray, rep: np.ndarray,
                     base_hover: np.ndarray, layout) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(slots, airport ordinals, mode minutes) for the cells to override.

    `last` is itinerary.arrival_airport_per_node, `acc` modes.mode_minutes_per_node,
    `rep` hover.representative_array (a node per hover parent), `base_hover` the
    hover parent of each base cell, `layout` hover.reading_layout -- whose
    `source` is the node each reading slot shows, so the override describes
    the journey behind the very number printed there.
    """
    src = layout.source
    rep_node = rep[base_hover]
    ok = (src >= 0) & (rep_node >= 0)
    own = np.where(ok, last[np.where(ok, src, 0)], -1)
    theirs = np.where(ok, last[np.where(ok, rep_node, 0)], -1)
    pick = np.flatnonzero(ok & (own != theirs))
    slots = layout.dest[pick].astype(np.int64)
    order = np.argsort(slots, kind="stable")
    pick, slots = pick[order], slots[order]
    nodes = src[pick]
    first_arrival = idx.n_cells + len(idx.airports)
    airport = np.where(last[nodes] >= 0, last[nodes] - first_arrival, NO_AIRPORT)
    minutes = np.clip(np.nan_to_num(acc[nodes], posinf=0.0), 0, MAX_MINUTES)
    return slots, airport, minutes


def write_override(idx, last, acc, rep, base_hover, layout, out: Path) -> int:
    slots, airport, minutes = override_entries(idx, last, acc, rep, base_hover, layout)
    _io.write_bytes(out, slots.astype("<u4").tobytes() + airport.astype("<u2").tobytes()
                    + minutes.astype("<u2").tobytes())
    return len(slots)
