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

Two finer points, both handled here:

  * A base cell can straddle a strait narrower than itself and touch both
    shores; 6,188 of 4,091,715 do. Where such a cell is split, its FINE_RES
    children are judged one by one (`fine_cell_parts`), open water going to the
    nearest shore -- Messina and the Helsingor narrows were each joined by
    exactly one straddler.
  * A bridge long enough to cross a water cell joins two cells that were never
    neighbours, so no edge existed for it to protect: the Great Belt, the
    Oresund Bridge and the Confederation Bridge were cut before any severing.
    `spanning_links` turns such road links into edges of their own.

What remains, stated rather than hidden: a straddler that was NOT split (open
country, no roads to speak of) still joins both shores at SOLVE_RES; and a
FINE_RES child that itself touches both shores still joins them.
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
                  linked: set[tuple[int, int]],
                  fine_parts: dict[str, tuple[int, ...]] | None = None
                  ) -> frozenset[tuple[int, int]]:
    """Ordered (u, v) graph-cell pairs that hex_edges would join but must not.

    `base_parts[i]` is the land parts base cell `base_cells[i]` touches; an
    empty tuple (the South Pole cells) never severs. `split` names the base
    cells replaced by their FINE_RES children in the graph.

    `fine_parts` gives the parts of individual FINE_RES children, and is only
    ever filled for children of a split base cell that STRADDLES a strait --
    one touching more than one part (`fine_cell_parts`). A straddler inherits
    both shores and so joined them: Messina and the Helsingor narrows were
    joined by exactly one such cell each. With its children judged one by one
    the strait is resolved down to FINE_RES, and siblings on opposite shores
    of it are severed from each other too.

    Candidates are found at base resolution, where most pairs share a part and
    are dismissed at once; only a surviving base pair is expanded to the graph
    cells that actually meet across it, judged by `refine.ground_adjacent` --
    the same test hex_edges and build use, so all three agree on what "joined"
    means.
    """
    fine_parts = fine_parts or {}
    base_pos = {c: i for i, c in enumerate(base_cells)}

    def graph_cells(base: str) -> list[str]:
        return h3.cell_to_children(base, config.FINE_RES) if base in split else [base]

    def parts_of(cell: str, base_i: int) -> tuple[int, ...]:
        return fine_parts.get(cell, base_parts[base_i])

    out: set[tuple[int, int]] = set()

    def judge(a: str, ia: int, b: str, ib: int) -> None:
        u, v = cell_pos.get(a), cell_pos.get(b)
        if u is None or v is None or (u, v) in linked:
            return
        pa, pb = parts_of(a, ia), parts_of(b, ib)
        if not pa or not pb or set(pa) & set(pb) or not ground_adjacent(a, b):
            return
        out.add((u, v))
        out.add((v, u))

    for i, base in enumerate(base_cells):
        pi = base_parts[i]
        if not pi:
            continue
        refined_i = base in split and len(pi) > 1
        if refined_i:
            kids = graph_cells(base)
            for x, a in enumerate(kids):
                for b in kids[x + 1:]:
                    judge(a, i, b, i)
        for nb in h3.grid_ring(base, 1):
            j = base_pos.get(nb)
            if j is None or j <= i:
                continue
            pj = base_parts[j]
            refined_j = nb in split and len(pj) > 1
            if not pj or (set(pi) & set(pj) and not refined_i and not refined_j):
                continue
            for a in graph_cells(base):
                for b in graph_cells(nb):
                    judge(a, i, b, j)
    return frozenset(out)


def fine_cell_parts(base_cells: list[str], base_parts: list[tuple[int, ...]],
                    split: set[str], polygons: list) -> dict[str, tuple[int, ...]]:
    """Land parts of each FINE_RES child of a split base cell that straddles.

    A child touching land is assigned the parts its hexagon intersects, among
    the base cell's own. A child holding only water is assigned the NEAREST of
    them: left inheriting both shores it would stay a free bridge across the
    strait, and every other assignment of open water is arbitrary. Nearest
    shore splits the water along the strait's midline.

    Antarctica is one landmass (`landmask.ANTARCTICA_LANDMASS`) and is never
    refined here; a straddler that includes it keeps its base parts.
    """
    import shapely

    from transport_maps.sources import landmask

    out: dict[str, tuple[int, ...]] = {}
    for base, parts in zip(base_cells, base_parts):
        if base not in split or len(parts) < 2 or landmask.ANTARCTICA_LANDMASS in parts:
            continue
        polys = {pid: polygons[pid] for pid in parts}
        for kid in h3.cell_to_children(base, config.FINE_RES):
            hexagon = shapely.Polygon([(lo, la) for la, lo in h3.cell_to_boundary(kid)])
            touched = tuple(sorted(pid for pid, poly in polys.items() if hexagon.intersects(poly)))
            if not touched:
                centre = shapely.Point(h3.cell_to_latlng(kid)[::-1])
                touched = (min(polys, key=lambda pid: polys[pid].distance(centre)),)
            out[kid] = touched
    return out


# Road class of an OSM highway, onto the GRIP classes whose speeds are FITTED in
# graph/ground.SPEED_BY_ROAD_CLASS_KMH. No new speed is introduced: a span over
# water is charged what the model charges the same class of road on land.
# Footways, cycleways, paths and the like are absent on purpose -- a walkway
# across a strait is not a road, and charging it at road speed would be false.
SPAN_ROAD_CLASS = {
    "motorway": 1, "motorway_link": 1, "trunk": 1, "trunk_link": 1,
    "primary": 2, "primary_link": 2,
    "secondary": 3, "secondary_link": 3,
    "tertiary": 4, "tertiary_link": 4,
    "unclassified": 5, "residential": 5, "road": 5, "service": 5, "living_street": 5,
}
# The longest fixed road link in service, the Hong Kong-Zhuhai-Macau crossing,
# is about 55 km including its tunnel. A "span" longer than this is a mapping
# error or two unrelated land cells, not a bridge.
MAX_SPAN_KM = 60.0


def spanning_links(links: pl.DataFrame,
                   cell_index_at: Callable[[float, float], int | None],
                   speed_kmh_by_class) -> dict[tuple[int, int], float]:
    """Road links that cross OFF the land mask and back: (u, v) -> minutes, both ways.

    `linked_pairs` joins only cells a link passes DIRECTLY between; a bridge
    long enough to cross a water cell joins two cells that were never
    neighbours, so hex_edges had no edge to keep and the crossing did not exist
    -- the Great Belt, the Oresund Bridge and the Confederation Bridge were all
    cut before any severing. This returns the land cell where each such span
    leaves land and the one where it arrives, costed along the link itself at
    its road class. Railway links are not returned: trains already cross on the
    rail graph.
    """
    out: dict[tuple[int, int], float] = {}
    for kind, highway, lats, lons in zip(links["kind"].to_list(), links["highway"].to_list(),
                                          links["lat"].to_list(), links["lon"].to_list()):
        cls = SPAN_ROAD_CLASS.get(highway) if kind == "highway" else None
        if cls is None:
            continue
        speed = float(speed_kmh_by_class[cls])
        last, last_km, km, gap = None, 0.0, 0.0, False
        for (la1, lo1), (la2, lo2) in zip(zip(lats, lons), zip(lats[1:], lons[1:])):
            if abs(lo2 - lo1) > 180.0:
                last, gap = None, False
                continue
            seg = _haversine_km(la1, lo1, la2, lo2)
            n = max(1, math.ceil(seg / LINK_STEP_KM))
            for k, t in enumerate(np.linspace(0.0, 1.0, n + 1)):
                here = cell_index_at(la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t)
                at_km = km + seg * t
                if here is None:
                    gap = gap or last is not None
                    continue
                if gap and last is not None and here != last and at_km - last_km <= MAX_SPAN_KM:
                    minutes = 60.0 * (at_km - last_km) / speed
                    for pair in ((last, here), (here, last)):
                        out[pair] = min(out.get(pair, math.inf), minutes)
                last, last_km, gap = here, at_km, False
            km += seg
    return out
