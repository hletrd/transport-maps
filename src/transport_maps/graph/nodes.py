"""Stable integer indices for every node in the multi-modal graph.

Layout: land cells occupy [0, n_cells), then airports. Keeping cells first means
the per-cell time surface is simply `distances[:n_cells]`.
"""

from dataclasses import dataclass

import h3

from transport_maps import config
from transport_maps.sources import airports, landmask


@dataclass(frozen=True)
class NodeIndex:
    cells: list[str]
    airports: list[str]
    _cell_pos: dict[str, int]
    _airport_pos: dict[str, int]
    _airport_cell: dict[str, int]

    @property
    def n_cells(self) -> int:
        return len(self.cells)

    @property
    def n(self) -> int:
        return len(self.cells) + len(self.airports)

    def cell_index(self, cell: str) -> int:
        return self._cell_pos[cell]

    def try_cell_index(self, cell: str) -> int | None:
        """Position of `cell`, or None when it is not a land cell."""
        return self._cell_pos.get(cell)

    def airport_index(self, iata: str) -> int:
        return self._airport_pos[iata]

    def airport_cell_index(self, iata: str) -> int:
        return self._airport_cell[iata]


def build_index() -> NodeIndex:
    cells = landmask.land_cells(config.SOLVE_RES)
    cell_pos = {c: i for i, c in enumerate(cells)}

    apts = airports.scheduled_airports()
    codes: list[str] = []
    airport_cell: dict[str, int] = {}
    for iata, lat, lon in zip(apts["iata"], apts["lat"], apts["lon"]):
        cell = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
        pos = cell_pos.get(cell)
        if pos is None:
            # Airport on a cell the land mask missed; skip rather than corrupt the graph.
            continue
        codes.append(iata)
        airport_cell[iata] = pos

    airport_pos = {code: len(cells) + i for i, code in enumerate(codes)}
    return NodeIndex(cells, codes, cell_pos, airport_pos, airport_cell)
