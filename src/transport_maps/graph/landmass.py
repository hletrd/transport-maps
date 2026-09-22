"""Which adjacent land cells open water separates, with no bridge or tunnel between.

`ground.hex_edges` joins every pair of adjacent land cells, and a land cell is
any cell touching land. At SOLVE_RES two cells on opposite shores of a strait
narrower than a cell are therefore neighbours, and the graph drove across the
sea: Saipan to Tinian, 8 km of open water, booked as 7.1 minutes of "major road".
Worse, `build._ferry_edges` then refused the crossing's real ferry as a
duplicate of that road, so the model invented one route and deleted another.

A pair of adjacent cells is SEVERED when

  * their base cells' hexagons touch no land part in common
    (`landmask.land_cell_landmasses`), and
  * no bridge or tunnel (`sources/fixed_links`) passes from one into the other.

Both halves are needed. Six rules built on geometry alone were measured and
all failed; so did landmass identity without the bridges, which splits every
bridged island chain. With both, on named cases (`scripts/check_fixed_links.py`),
the Great Seto, Akashi-Kaikyo and Naruto bridges stay joined while Shodoshima
and Tinian, which only ferries and aircraft reach, are cut.

Limits, stated rather than hidden:

  * Parts are judged per BASE cell and carried down to its fine children, so a
    base cell straddling a strait touches both shores and joins them. A strait
    narrower than a cell stays joined, as before: Messina (~3 km), and the
    Helsingor-Helsingborg narrows (~4 km), which only ferries cross -- that is
    what joins Zealand to Sweden in the graph.
  * A bridge whose span crosses a water cell links two cells that were never
    neighbours. It cannot protect an edge that does not exist and this module
    adds none. Measured cut before and after this rule: the Great Belt, the
    Confederation Bridge, and the Oresund Bridge within its own area.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import h3
import numpy as np
import polars as pl

from transport_maps import config

from .refine import ground_adjacent

# Sampling step along a fixed link. A FINE_RES edge is about 1.4 km, so a step
# this short cannot skip a cell, and consecutive samples always land in one
# cell or in two neighbouring ones.
LINK_STEP_KM = 0.25


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def linked_pairs(links: pl.DataFrame,
                 cell_index_at: Callable[[float, float], int | None]) -> set[tuple[int, int]]:
    """Ordered (u, v) graph-cell pairs that a fixed link passes directly between.

    `cell_index_at(lat, lon)` gives the graph position of the cell at a point,
    or None off the land mask. A span that leaves the land mask on the way --
    a water cell between -- links nothing across the gap.
    """
    pairs: set[tuple[int, int]] = set()
    for lats, lons in zip(links["lat"].to_list(), links["lon"].to_list()):
        prev = None
        for (la1, lo1), (la2, lo2) in zip(zip(lats, lons), zip(lats[1:], lons[1:])):
            # A segment across the antimeridian would be interpolated the long
            # way round the globe; no fixed link is worth that risk.
            if abs(lo2 - lo1) > 180.0:
                prev = None
                continue
            n = max(1, math.ceil(_haversine_km(la1, lo1, la2, lo2) / LINK_STEP_KM))
            for t in np.linspace(0.0, 1.0, n + 1):
                here = cell_index_at(la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t)
                if here is not None and prev is not None and here != prev:
                    pairs.add((prev, here))
                    pairs.add((here, prev))
                prev = here
    return pairs


def severed_pairs(base_cells: list[str], base_parts: list[tuple[int, ...]],
                  split: set[str], cell_pos: dict[str, int],
                  linked: set[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    """Ordered (u, v) graph-cell pairs that hex_edges would join but must not.

    `base_parts[i]` is the land parts base cell `base_cells[i]` touches; an
    empty tuple (the South Pole cells) never severs. `split` names the base
    cells replaced by their FINE_RES children in the graph.

    Candidates are found at base resolution, where most pairs share a part and
    are dismissed at once; only a surviving base pair is expanded to the graph
    cells that actually meet across it, judged by `refine.ground_adjacent` --
    the same test hex_edges and build use, so all three agree on what "joined"
    means.
    """
    base_pos = {c: i for i, c in enumerate(base_cells)}

    def graph_cells(base: str) -> list[str]:
        return h3.cell_to_children(base, config.FINE_RES) if base in split else [base]

    out: set[tuple[int, int]] = set()
    for i, base in enumerate(base_cells):
        pi = base_parts[i]
        if not pi:
            continue
        for nb in h3.grid_ring(base, 1):
            j = base_pos.get(nb)
            if j is None or j <= i:
                continue
            pj = base_parts[j]
            if not pj or set(pi) & set(pj):
                continue
            for a in graph_cells(base):
                u = cell_pos.get(a)
                if u is None:
                    continue
                for b in graph_cells(nb):
                    v = cell_pos.get(b)
                    if v is None or (u, v) in linked or not ground_adjacent(a, b):
                        continue
                    out.add((u, v))
                    out.add((v, u))
    return frozenset(out)
