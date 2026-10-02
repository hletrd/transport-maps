"""Where each kind of node sits in the solver's id space.

One description of the layout `graph/nodes.py` builds and every emitter reads,
in place of the offsets each module used to derive by hand (docs/contract.md,
"Node-offset arithmetic"):

    [0, C)                  land cells
    [C, C+N)                airport departure nodes, in airport order
    [C+N, C+2N)             airport arrival nodes
    [C+2N, C+2N+S)          rail stations
    [C+2N+S, C+3N+S)        international departure nodes (see graph/build.py)
    [C+3N+S, C+4N+S)        international arrival nodes

C cells, N airports, S stations. The international ranges come after the
stations so that adding them moved no id the page or an older file knows.

Pure arithmetic on three counts, with no import of the graph package, so the
emitters, the solver service and test doubles of the index can all use it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NodeLayout:
    n_cells: int
    n_airports: int
    n_stations: int = 0

    @property
    def first_departure(self) -> int:
        return self.n_cells

    @property
    def first_arrival(self) -> int:
        return self.n_cells + self.n_airports

    @property
    def first_station(self) -> int:
        return self.n_cells + 2 * self.n_airports

    @property
    def first_intl_departure(self) -> int:
        return self.first_station + self.n_stations

    @property
    def first_intl_arrival(self) -> int:
        return self.first_intl_departure + self.n_airports

    @property
    def n(self) -> int:
        return self.first_intl_arrival + self.n_airports

    def is_station(self, node):
        """True for a rail station node; elementwise over an array."""
        return (node >= self.first_station) & (node < self.first_intl_departure)

    def is_arrival(self, node):
        """True for an arrival node of either layer; elementwise over an array."""
        return (((node >= self.first_arrival) & (node < self.first_station))
                | ((node >= self.first_intl_arrival) & (node < self.n)))

    def arrival_ordinal(self, node):
        """The airport ordinal of an arrival node of either layer, else -1.
        The ordinal is the airport's position in the index, the number
        `.air.bin` and `.over.bin` carry. Elementwise over an array."""
        node = np.asarray(node)
        out = np.where((node >= self.first_arrival) & (node < self.first_station),
                       node - self.first_arrival,
                       np.where((node >= self.first_intl_arrival) & (node < self.n),
                                node - self.first_intl_arrival, -1))
        return int(out) if out.ndim == 0 else out


def layout_of(idx) -> NodeLayout:
    """The layout of a NodeIndex, or of anything with its `n_cells`,
    `airports` and (optionally) `stations`."""
    return NodeLayout(int(idx.n_cells), len(idx.airports),
                      len(getattr(idx, "stations", None) or ()))
