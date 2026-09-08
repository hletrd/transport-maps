"""Stable integer indices for every node in the multi-modal graph.

Layout: land cells occupy [0, n_cells), then one DEPARTURE node per airport,
then one ARRIVAL node per airport. Keeping cells first means the per-cell time
surface is still simply `distances[:n_cells]`.

Airports are split because a single node cannot tell a journey's first flight
from a connecting one. With one node, the minimum-connection-time had to be
charged on every flight edge, so every journey paid a connection penalty for a
leg that was never a connection -- about 75 minutes of pure error on a
one-flight trip. Splitting makes the distinction structural:

    cell -> A_dep     access: reach the airport, check in, board
    A_dep -> B_arr    the flight itself
    B_arr -> B_dep    a connection, and only ever a connection
    B_arr -> cell     egress: disembark and leave the airport
"""

import logging
from dataclasses import dataclass

import h3

from transport_maps import config
from transport_maps.sources import airports, landmask

# An airport whose containing H3 cell is absent from the land mask cannot be
# wired into the graph, so it is dropped. A handful is normal and permanent:
# 25 of 4,008 today (0.62%), all on islands and coastal spits finer than the
# 10m coastline. Thousands would mean the land mask itself regressed -- which
# NOTHING else would catch, because the 90% publication gate measures land
# CELLS, not airports, and would still pass with every airport on Earth gone.
MAX_DROPPED_AIRPORT_FRACTION = 0.02

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeIndex:
    cells: list[str]
    airports: list[str]
    _cell_pos: dict[str, int]
    _airport_pos: dict[str, int]
    _airport_cell: dict[str, int]
    # Scheduled-service airports the land mask had no cell for. Exposed rather
    # than merely logged so a caller (or a test) can inspect exactly what was
    # dropped, the same way build_graph exposes its rejected long-haul pairs.
    dropped_airports: tuple[str, ...] = ()

    @property
    def n_cells(self) -> int:
        return len(self.cells)

    @property
    def n(self) -> int:
        return len(self.cells) + 2 * len(self.airports)

    def cell_index(self, cell: str) -> int:
        return self._cell_pos[cell]

    def try_cell_index(self, cell: str) -> int | None:
        """Position of `cell`, or None when it is not a land cell."""
        return self._cell_pos.get(cell)

    def airport_index(self, iata: str) -> int:
        """Departure-side node: where you board."""
        return self._airport_pos[iata]

    def airport_arr_index(self, iata: str) -> int:
        """Arrival-side node: where you land, before connecting or leaving."""
        return self._airport_pos[iata] + len(self.airports)

    def airport_cell_index(self, iata: str) -> int:
        return self._airport_cell[iata]


def build_index() -> NodeIndex:
    cells = landmask.land_cells(config.SOLVE_RES)
    cell_pos = {c: i for i, c in enumerate(cells)}

    apts = airports.scheduled_airports()
    codes: list[str] = []
    dropped: list[str] = []
    airport_cell: dict[str, int] = {}
    for iata, lat, lon in zip(apts["iata"], apts["lat"], apts["lon"]):
        cell = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
        pos = cell_pos.get(cell)
        if pos is None:
            # Airport on a cell the land mask missed; skip rather than corrupt
            # the graph. Counted and bounded below -- an unbounded silent skip
            # is how a land-mask regression would reach dist/ unnoticed.
            dropped.append(iata)
            continue
        codes.append(iata)
        airport_cell[iata] = pos

    if dropped:
        logger.warning(
            "%d of %d scheduled-service airport(s) dropped: no land cell at their "
            "location (%s%s)",
            len(dropped), len(apts), ", ".join(dropped[:10]),
            ", ..." if len(dropped) > 10 else "",
        )
    limit = MAX_DROPPED_AIRPORT_FRACTION * len(apts)
    if len(dropped) > limit:
        raise RuntimeError(
            f"{len(dropped)} of {len(apts)} scheduled-service airports have no land "
            f"cell, above the {MAX_DROPPED_AIRPORT_FRACTION:.0%} bound ({limit:.0f}); "
            "the land mask has regressed -- note the coverage gate would NOT catch "
            "this, as it measures land cells rather than airports"
        )

    airport_pos = {code: len(cells) + i for i, code in enumerate(codes)}
    return NodeIndex(cells, codes, cell_pos, airport_pos, airport_cell, tuple(dropped))
