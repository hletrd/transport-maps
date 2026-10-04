"""Which adjacent land cells open water separates, with no road between.

`ground.hex_edges` joins every pair of adjacent land cells, and a land cell is
any cell touching land. At SOLVE_RES two cells on opposite shores of a strait
narrower than a cell are therefore neighbours, and the graph drove across the
sea: Saipan to Tinian, 8 km of open water, booked as 7.1 minutes of "major road".
Worse, `build._ferry_edges` then refused the crossing's real ferry as a
duplicate of that road, so the model invented one route and deleted another.

A pair of adjacent cells is SEVERED when

  * their base cells' hexagons touch no land part in common
    (`landmask.land_cell_landmasses`), and
  * no road passes from one into the other: no bridge or tunnel
    (`sources/fixed_links`), and no plain road across the seam
    (`sources/road_crossings`) -- a seawall, a polder dike, a causeway.

Both halves are needed. Six rules built on geometry alone were measured and
all failed; so did landmass identity without the bridges, which splits every
bridged island chain. With both, on named cases (`scripts/check_fixed_links.py`),
the Great Seto, Akashi-Kaikyo and Naruto bridges stay joined while Shodoshima
and Tinian, which only ferries and aircraft reach, are cut. Bridges and
tunnels alone were not enough either: the Sihwa seawall, Jido's polder roads
and the islet between the Apdo Bridge's decks carry neither tag, and
Daebu-do, Jido and Apdo were cut (2026-10-04, A16).

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

What remains, stated rather than hidden: a FINE_RES child that itself touches
both shores still joins them. (A straddler that was not split -- open country,
no roads to speak of -- used to join both shores at SOLVE_RES too; since
2026-10-02 every straddler is split, graph/refine.straddler_mask.)
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
# Link kinds that carry a road: a bridge or tunnel (sources/fixed_links) and a
# plain road across a land-part seam (sources/road_crossings). Railways cross
# on the rail graph and are never a span.
ROAD_KINDS = frozenset({"highway", "road"})
# The longest fixed road link in service, the Hong Kong-Zhuhai-Macau crossing,
# is about 55 km including its tunnel. A "span" longer than this is a mapping
# error or two unrelated land cells, not a bridge.
MAX_SPAN_KM = 60.0
# A fixed link that dead-ends over "water" has, in fact, landed on land the
# land mask does not have: OSM tags only the bridge and tunnel sections, and
# Natural Earth's 1:10M coast omits islets such as Sprogo (Great Belt) and
# Peberholm (Oresund) and runs a cell short of shore at Cape Jourimain
# (Confederation Bridge). Only major roads (GRIP classes 1-3) are continued this
# way, so a pier or a ferry ramp -- service roads -- never is.
ISLET_MAX_CLASS = 3
# Two such dead ends this close are the two halves of one crossing, joined by
# the at-grade road across the islet: Sprogo's gap is 3.2 km, Peberholm's ~3.5.
MAX_ISLET_KM = 5.0


def split_spans(spans: dict[tuple[int, int], float], linked: set[tuple[int, int]],
                cells: list[str]) -> tuple[dict[tuple[int, int], float], set[tuple[int, int]]]:
    """Spans between grid NEIGHBOURS are protected adjacencies, not edges.

    A bridge can dip through a water cell between two cells that are grid
    neighbours. As an edge it would duplicate the ground edge hex_edges already
    builds between them, and build_graph refuses a duplicate (row, col) pair --
    the whole build would stop at the graph. What such a crossing really says
    is "these neighbours ARE joined by land", which is what `linked` means: it
    keeps the pair from being severed. Only spans between non-neighbours
    remain edges of their own.
    """
    kept: dict[tuple[int, int], float] = {}
    linked = set(linked)
    for (u, v), minutes in spans.items():
        if ground_adjacent(cells[u], cells[v]):
            linked.add((u, v))
        else:
            kept[(u, v)] = minutes
    return kept, linked


def spanning_links(links: pl.DataFrame,
                   cell_index_at: Callable[[float, float], int | None],
                   speed_kmh_by_class) -> dict[tuple[int, int], float]:
    """Road links that cross OFF the land mask and back: (u, v) -> minutes, both ways.

    `linked_pairs` joins only cells a link passes DIRECTLY between; a bridge
    long enough to cross a water cell joins two cells that were never
    neighbours, so hex_edges had no edge to keep and the crossing did not exist
    -- the Great Belt, the Oresund Bridge and the Confederation Bridge were all
    cut before any severing. This finds, for every such crossing, the land cell
    where it leaves land and the one where it arrives, costed along the link at
    each piece's own road class. Railway links are not returned: trains
    already cross on the rail graph. A plain road across cells the land mask
    lacks -- the Sihwa seawall's 12.7 km -- is a span the same way (kind
    "road", sources/road_crossings), but is never continued past a dead end.

    **Ways are stitched, not taken one at a time.** OSM splits a long crossing
    into several ways -- the bridge deck, a tunnel, the approach viaducts --
    that meet end to end OVER THE WATER, sharing a node there. Judged way by
    way, none of them runs from land to land, and the first version of this
    found no span at all for the Great Belt, the Oresund, the Confederation
    Bridge or the Busan-Geoje link. Every sample becomes a vertex (a way's own
    nodes keyed by coordinate, so ways sharing a node share the vertex), and a
    crossing is a path through water vertices between two land vertices.
    """
    import heapq

    Vertex = tuple
    cell_of: dict[Vertex, int | None] = {}
    adj: dict[Vertex, list[tuple[Vertex, float, float]]] = {}
    # For the dead-end rules: where each way's end node is, and the slowest
    # class that ends there (a major road only if every way there is one).
    end_at: dict[Vertex, tuple[float, float]] = {}
    end_class: dict[Vertex, int] = {}

    def vertex(key: Vertex, lat: float, lon: float) -> Vertex:
        if key not in cell_of:
            cell_of[key] = cell_index_at(lat, lon)
        return key

    def join(a: Vertex, b: Vertex, km: float, minutes: float) -> None:
        adj.setdefault(a, []).append((b, km, minutes))
        adj.setdefault(b, []).append((a, km, minutes))

    for row, (kind, highway, lats, lons) in enumerate(zip(
            links["kind"].to_list(), links["highway"].to_list(),
            links["lat"].to_list(), links["lon"].to_list())):
        cls = SPAN_ROAD_CLASS.get(highway) if kind in ROAD_KINDS else None
        if cls is None:
            continue
        speed = float(speed_kmh_by_class[cls])
        # Only a bridge or tunnel is continued past a dead end over water. A
        # plain road that stops "over water" stops at a coast the mask draws
        # too far inland -- a quay, a slipway, a ferry ramp -- and two of them
        # 5 km apart on facing shores are two ferry terminals, not an islet.
        ends = kind == "highway"
        for s, ((la1, lo1), (la2, lo2)) in enumerate(zip(zip(lats, lons), zip(lats[1:], lons[1:]))):
            if abs(lo2 - lo1) > 180.0:
                continue
            seg = _haversine_km(la1, lo1, la2, lo2)
            n = max(1, math.ceil(seg / LINK_STEP_KM))
            prev = vertex(("n", round(la1, 7), round(lo1, 7)), la1, lo1)
            if s == 0 and ends:
                end_at[prev] = (la1, lo1)
                end_class[prev] = max(end_class.get(prev, 0), cls)
            for k in range(1, n + 1):
                t = k / n
                if k == n:
                    here = vertex(("n", round(la2, 7), round(lo2, 7)), la2, lo2)
                    if s == len(lats) - 2 and ends:
                        end_at[here] = (la2, lo2)
                        end_class[here] = max(end_class.get(here, 0), cls)
                else:
                    # Keyed by row, not way id: one road way can give several
                    # stretches (sources/road_crossings), and their samples
                    # must not be taken for one another's.
                    la, lo = la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t
                    here = vertex(("s", row, s, k), la, lo)
                step = seg / n
                join(prev, here, step, 60.0 * step / speed)
                prev = here

    _continue_dead_ends(cell_of, adj, end_at, end_class, cell_index_at, speed_kmh_by_class,
                        join)

    out: dict[tuple[int, int], float] = {}
    # From every land vertex that touches water, walk through water only.
    for start, start_cell in cell_of.items():
        if start_cell is None or not any(cell_of[w] is None for w, _, _ in adj.get(start, ())):
            continue
        best = {start: 0.0}
        heap = [(0.0, 0.0, start)]
        while heap:
            minutes, km, v = heapq.heappop(heap)
            if minutes > best.get(v, math.inf):
                continue
            for w, step_km, step_min in adj.get(v, ()):
                nkm, nmin = km + step_km, minutes + step_min
                if nkm > MAX_SPAN_KM or nmin >= best.get(w, math.inf):
                    continue
                best[w] = nmin
                target = cell_of[w]
                if target is None:
                    heapq.heappush(heap, (nmin, nkm, w))
                elif target != start_cell and v != start:
                    # Arrived on land after crossing water: a span. (`v !=
                    # start` is belt and braces: a direct land-to-land step is
                    # what linked_pairs records, and split_spans would turn
                    # such a pair into a protected adjacency anyway -- dropping
                    # it was measured an equivalent mutation.)
                    for pair in ((start_cell, target), (target, start_cell)):
                        out[pair] = min(out.get(pair, math.inf), nmin)
    return out


def _continue_dead_ends(cell_of, adj, end_at, end_class, cell_index_at, speed_kmh_by_class,
                        join) -> None:
    """Continue major-road fixed links that dead-end over water (ISLET_MAX_CLASS).

    Landfall: a dead end joins the nearest land cell in the ring around it.
    Islet: two dead ends within MAX_ISLET_KM join each other. Both are costed
    as straight lines at the slower class of the two ends.
    """
    import h3
    import numpy as np
    from scipy.spatial import cKDTree

    # `cell_of[v] is None`: an end on land needs nothing continued. Dropping
    # the test was measured an equivalent mutation -- a land end's extra edge
    # reaches only land, and the search never walks land to land -- so it is
    # kept for what it says rather than for anything a test can see.
    dead = [v for v, (la, lo) in end_at.items()
            if cell_of[v] is None and len(adj.get(v, ())) == 1
            and end_class.get(v, 99) <= ISLET_MAX_CLASS]
    for v in dead:
        la, lo = end_at[v]
        best = None
        for n in h3.grid_ring(h3.latlng_to_cell(la, lo, config.SOLVE_RES), 1):
            c = cell_index_at(*h3.cell_to_latlng(n))
            if c is None:
                continue
            km = _haversine_km(la, lo, *h3.cell_to_latlng(n))
            if best is None or km < best[1]:
                best = (c, km)
        if best is not None:
            land = ("land", best[0])
            cell_of.setdefault(land, best[0])
            speed = float(speed_kmh_by_class[end_class[v]])
            join(v, land, best[1], 60.0 * best[1] / speed)
    if len(dead) < 2:
        return
    ll = np.radians(np.array([end_at[v] for v in dead]))
    xyz = np.column_stack([np.cos(ll[:, 0]) * np.cos(ll[:, 1]),
                           np.cos(ll[:, 0]) * np.sin(ll[:, 1]), np.sin(ll[:, 0])])
    chord = 2 * math.sin(MAX_ISLET_KM / 6371.0088 / 2)
    for i, j in cKDTree(xyz).query_pairs(chord):
        a, b = dead[i], dead[j]
        km = _haversine_km(*end_at[a], *end_at[b])
        speed = float(speed_kmh_by_class[max(end_class[a], end_class[b])])
        join(a, b, km, 60.0 * km / speed)
