"""Stable integer indices for every node in the multi-modal graph.

Layout: land cells occupy [0, n_cells), then one DEPARTURE node per airport,
then one ARRIVAL node per airport, then one node per rail station. Keeping
cells first means the per-cell time surface is still simply
`distances[:n_cells]`, and appending stations last means adding rail does not
move any airport index.

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
from dataclasses import dataclass, field

import h3
import numpy as np

from transport_maps import config
from transport_maps.sources import airports, landmask

# An airport whose containing H3 cell is absent from the land mask is snapped
# to the nearest indexed cell within two rings (_nearest_land); one with no
# land cell that close cannot be wired into the graph and is dropped. A handful
# is normal and permanent: at resolution 6 about a dozen atolls of 4,008 are
# dropped and about 46 are snapped (2026-09). Thousands would mean the land
# mask itself regressed -- which NOTHING else would catch, because the 90%
# publication gate measures land CELLS, not airports, and would still pass
# with every airport on Earth gone.
MAX_DROPPED_AIRPORT_FRACTION = 0.02
# The snap makes the dropped bound blind to a mask that lost its coast: every
# coastal airport would be snapped one cell inland and the build would pass.
# Bound the snapped share too.
MAX_SNAPPED_AIRPORT_FRACTION = 0.05

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
    # Rail is optional: the OSM extracts are tens of gigabytes and may not be
    # present. Empty stations means a road-and-air graph, which is a valid
    # build -- but callers are told which they got rather than left to guess.
    stations: tuple[str, ...] = ()
    # The uniform resolution-6 grid the cells were refined from (graph/refine.py),
    # the position in it of every cell's base self-or-parent, which cells are
    # the finer children, and which base cells were split. Per-base-cell inputs
    # (road class, urban mask) are expanded through base_index rather than
    # recomputed for millions of children.
    base_cells: list[str] = field(default_factory=list)
    base_index: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    fine: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    _split: frozenset = frozenset()
    _station_pos: dict[str, int] = field(default_factory=dict)
    _station_cell: dict[str, int] = field(default_factory=dict)

    @property
    def n_cells(self) -> int:
        return len(self.cells)

    @property
    def n(self) -> int:
        return len(self.cells) + 2 * len(self.airports) + len(self.stations)

    @property
    def has_rail(self) -> bool:
        return bool(self.stations)

    def cell_index(self, cell: str) -> int:
        return self._cell_pos[cell]

    def cell_at(self, lat: float, lon: float) -> str:
        """The cell of this index at a point: the fine cell where the base
        cell was split, else the base cell. May not be a land cell."""
        base = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
        if base in self._split:
            return h3.latlng_to_cell(lat, lon, config.FINE_RES)
        return base

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

    def station_index(self, station: str) -> int:
        return self._station_pos[station]

    def station_cell_index(self, station: str) -> int:
        """The land cell a station sits in, which is how you reach it."""
        return self._station_cell[station]


def _nearest_land(cell: str, cell_pos: dict[str, int], lat: float, lon: float,
                  split: frozenset | set = frozenset()) -> tuple[int, float] | None:
    """The nearest indexed cell within two rings of `cell`: (position, km), or None.

    Ring neighbours are looked up at `cell`'s own resolution. A neighbour that
    is absent from the index because it was SPLIT (it is present only as its
    FINE_RES children) contributes those children instead; a fine neighbour
    whose base cell was not split contributes that base cell. Without the
    split case every dense coastal cell -- exactly the land beside a
    reclaimed-island airport -- was invisible to the search: Kitakyushu was
    dropped with land 5 km away and Bodø was wired to a cell 11 km off past six
    adjacent land cells. Every candidate across both rings is compared by
    distance, so "nearest" means nearest and not first-found.
    """
    best: tuple[int, float] | None = None
    for ring in (1, 2):
        for n in h3.grid_ring(cell, ring):
            if n in cell_pos:
                candidates = (n,)
            elif n in split:
                candidates = h3.cell_to_children(n, config.FINE_RES)
            elif h3.get_resolution(n) > config.SOLVE_RES:
                candidates = (h3.cell_to_parent(n, config.SOLVE_RES),)
            else:
                continue
            for candidate in candidates:
                pos = cell_pos.get(candidate)
                if pos is None:
                    continue
                km = h3.great_circle_distance((lat, lon), h3.cell_to_latlng(candidate), unit="km")
                if best is None or km < best[1]:
                    best = (pos, km)
    return best


def _place_airports(apts, cell_pos: dict[str, int], split_set: set | frozenset
                    ) -> tuple[list[str], dict[str, int], list[str]]:
    """Each airport's land cell: its own, the nearest within two rings, or
    dropped. Returns (kept codes, code -> cell position, dropped codes) and
    enforces the dropped and snapped bounds."""
    def cell_at(lat, lon):
        base = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
        return h3.latlng_to_cell(lat, lon, config.FINE_RES) if base in split_set else base

    codes: list[str] = []
    dropped: list[str] = []
    snapped: list[tuple[str, float]] = []
    airport_cell: dict[str, int] = {}
    for iata, lat, lon in zip(apts["iata"], apts["lat"], apts["lon"]):
        cell = cell_at(lat, lon)
        pos = cell_pos.get(cell)
        if pos is None:
            # An airport is on land by definition; when its cell is not in the
            # mask (reclaimed islands, atolls, a shore the 1:10m outline cuts
            # inside), the nearest land cell within two rings stands in: two
            # rings at resolution 6 reach about 13 km, and most snaps are one
            # cell over. 58 of 4,008 airports needed it at resolution 6.
            found = _nearest_land(cell, cell_pos, lat, lon, split_set)
            if found is not None:
                pos, km = found
                snapped.append((iata, km))
        if pos is None:
            # Airport on a cell the land mask missed; skip rather than corrupt
            # the graph. Counted and bounded below -- an unbounded silent skip
            # is how a land-mask regression would reach dist/ unnoticed.
            dropped.append(iata)
            continue
        codes.append(iata)
        airport_cell[iata] = pos

    if snapped:
        worst = sorted(snapped, key=lambda s: -s[1])
        # WARNING, not INFO: this is the line that says where an airport was
        # moved to, and it must be visible in the build log.
        logger.warning("%d airport(s) snapped to the nearest land cell within two rings (%s%s)",
                       len(snapped), ", ".join(f"{i} {km:.1f} km" for i, km in worst[:8]),
                       ", ..." if len(snapped) > 8 else "")
    if dropped:
        logger.warning(
            "%d of %d scheduled-service airport(s) dropped: no land cell within two "
            "rings of their location (%s%s)",
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
    snap_limit = MAX_SNAPPED_AIRPORT_FRACTION * len(apts)
    if len(snapped) > snap_limit:
        raise RuntimeError(
            f"{len(snapped)} of {len(apts)} scheduled-service airports had to be snapped "
            f"to a neighbouring cell, above the {MAX_SNAPPED_AIRPORT_FRACTION:.0%} bound "
            f"({snap_limit:.0f}); the land mask has lost its coast"
        )
    return codes, airport_cell, dropped


def build_index(rail_routes=None) -> NodeIndex:
    """Build the node index. `rail_routes` is an osm.rail_routes() frame, or
    None to build a road-and-air graph."""
    base_cells = landmask.land_cells(config.SOLVE_RES)
    from transport_maps.sources import roads, urban

    from . import refine
    split = refine.dense_mask(roads.cell_class(base_cells), urban.urban_mask(base_cells))
    cells, base_index, fine = refine.refine(base_cells, split)
    logger.info("%d of %d base cells split into %d fine cells; %d cells in all",
                int(split.sum()), len(base_cells), int(fine.sum()), len(cells))
    cell_pos = {c: i for i, c in enumerate(cells)}
    split_set = {base_cells[i] for i in np.flatnonzero(split)}

    def cell_at(lat, lon):
        base = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
        return h3.latlng_to_cell(lat, lon, config.FINE_RES) if base in split_set else base

    codes, airport_cell, dropped = _place_airports(airports.scheduled_airports(), cell_pos, split_set)

    airport_pos = {code: len(cells) + i for i, code in enumerate(codes)}

    station_keys: list[str] = []
    station_pos: dict[str, int] = {}
    station_cell: dict[str, int] = {}
    if rail_routes is not None:
        from . import rail as rail_mod

        base = len(cells) + 2 * len(codes)
        dropped_stations = 0
        for row in rail_mod.stations(rail_routes).iter_rows(named=True):
            pos = cell_pos.get(cell_at(row["lat"], row["lon"]))
            if pos is None:
                # Station on a cell the land mask lacks -- coastal or islet.
                dropped_stations += 1
                continue
            station_pos[row["station"]] = base + len(station_keys)
            station_cell[row["station"]] = pos
            station_keys.append(row["station"])
        logger.info("%d rail station(s) indexed, %d dropped for want of a land cell",
                    len(station_keys), dropped_stations)

    return NodeIndex(cells, codes, cell_pos, airport_pos, airport_cell, tuple(dropped),
                     tuple(station_keys), _station_pos=station_pos, _station_cell=station_cell,
                     base_cells=base_cells, base_index=base_index, fine=fine,
                     _split=frozenset(split_set))
