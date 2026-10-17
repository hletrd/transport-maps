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
                    split: set[str], polygons: list,
                    water: set[str] | None = None) -> dict[str, tuple[int, ...]]:
    """Land parts of each FINE_RES child of a split base cell that straddles.

    A child touching land is assigned the parts its hexagon intersects, among
    the base cell's own. A child holding only water is assigned the NEAREST of
    them: left inheriting both shores it would stay a free bridge across the
    strait, and every other assignment of open water is arbitrary. Nearest
    shore splits the water along the strait's midline.

    Antarctica is one landmass (`landmask.ANTARCTICA_LANDMASS`) and is never
    refined here; a straddler that includes it keeps its base parts.

    `water`, when given, receives those water-only children: their shore is
    a guess, which `shore_landings` lets a ferry correct.
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
                if water is not None:
                    water.add(kid)
            out[kid] = touched
    return out


def shore_landings(fine_parts: dict[str, tuple[int, ...]], water: set[str],
                   cell_pos: dict[str, int]) -> dict[int, tuple[int, ...]]:
    """Graph cells a ferry landing in a water-only straddler child may mean.

    Such a child is given the nearest shore (`fine_cell_parts`), and that
    shore is only as right as Natural Earth's 1:10M coast. A pier is where
    the coast is, so a landing is the one place that coast is wrong by
    definition: Rupat's at Tanjung Kapal lies 2.9 km off Sumatra's NE coast
    and 3.5 km off Rupat's, so its cell went to Sumatra, the Dumai ferry
    joined Sumatra to Sumatra, and the island read "no route" from every
    origin (2026-10-06). For each such child this gives, per land part its
    siblings touch, the sibling nearest to it that touches that part; a
    ferry landing there is offered on every shore of the strait, and the
    sailing to the shore it starts from is longer than the road, so only the
    crossing it is for is ever taken.
    """
    by_base: dict[str, list[str]] = {}
    for kid in fine_parts:
        by_base.setdefault(h3.cell_to_parent(kid, config.SOLVE_RES), []).append(kid)
    out: dict[int, tuple[int, ...]] = {}
    for kid in water:
        here = cell_pos.get(kid)
        if here is None:
            continue
        lat, lon = h3.cell_to_latlng(kid)
        land = [s for s in by_base.get(h3.cell_to_parent(kid, config.SOLVE_RES), [])
                if s not in water and s in cell_pos]
        options = set()
        for part in {p for s in land for p in fine_parts[s]}:
            near = min((s for s in land if part in fine_parts[s]),
                       key=lambda s: _haversine_km(lat, lon, *h3.cell_to_latlng(s)))
            options.add(cell_pos[near])
        if options:
            out[here] = tuple(sorted(options))
    return out


# Road class of an OSM highway, onto the GRIP classes whose speeds are FITTED in
# graph/ground.SPEED_BY_ROAD_CLASS_KMH. No new speed is introduced: a span over
# water is charged what the model charges the same class of road on land.
# Footways, cycleways, paths and the like are absent on purpose -- a walkway
# across a strait is not a road, and charging it at road speed would be false.
#
# A motorway is the OSM motorway class, 6 (graph/ground.MOTORWAY_CLASS; a
# literal here because graph/ground imports this module through graph/nodes,
# and tests/graph/test_landmass.py holds the two equal). A trunk span stays
# GRIP4's highway: the fixed-link parse keeps no maxspeed, so the motorway
# rule (sources/motorways.RULE) cannot be asked of it.
SPAN_ROAD_CLASS = {
    "motorway": 6, "motorway_link": 6, "trunk": 1, "trunk_link": 1,
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


def _rank(cls: int) -> float:
    """How minor a span class is: GRIP4's own order, 1 highway .. 5 local,
    with the motorway class (6) above highway rather than below local."""
    return 0.5 if cls == SPAN_ROAD_CLASS["motorway"] else float(cls)


def _minor(a: int | None, b: int) -> int:
    """The more minor of two span classes (`a` None for none yet)."""
    return b if a is None or _rank(b) >= _rank(a) else a
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
    # How many bridge and tunnel steps meet at each vertex. An end is dead by
    # THIS count, not by everything joined there: a plain road stretch on a
    # causeway's embankment, itself stopping over water, used to make the
    # bridge end it touched look live -- and the King Fahd Causeway, which was
    # continued from islet to islet before road stretches were read, was cut
    # (measured 2026-10-04, Bahrain).
    bridge_degree: dict[Vertex, int] = {}

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
                end_class[prev] = _minor(end_class.get(prev), cls)
            for k in range(1, n + 1):
                t = k / n
                if k == n:
                    here = vertex(("n", round(la2, 7), round(lo2, 7)), la2, lo2)
                    if s == len(lats) - 2 and ends:
                        end_at[here] = (la2, lo2)
                        end_class[here] = _minor(end_class.get(here), cls)
                else:
                    # Keyed by row, not way id: one road way can give several
                    # stretches (sources/road_crossings), and their samples
                    # must not be taken for one another's.
                    la, lo = la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t
                    here = vertex(("s", row, s, k), la, lo)
                step = seg / n
                join(prev, here, step, 60.0 * step / speed)
                if ends:
                    bridge_degree[prev] = bridge_degree.get(prev, 0) + 1
                    bridge_degree[here] = bridge_degree.get(here, 0) + 1
                prev = here

    _continue_dead_ends(cell_of, bridge_degree, end_at, end_class, cell_index_at,
                        speed_kmh_by_class, join)

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


def _continue_dead_ends(cell_of, bridge_degree, end_at, end_class, cell_index_at,
                        speed_kmh_by_class, join) -> None:
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
            if cell_of[v] is None and bridge_degree.get(v, 0) == 1
            and v in end_class and _rank(end_class[v]) <= ISLET_MAX_CLASS]
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
        speed = float(speed_kmh_by_class[_minor(end_class[a], end_class[b])])
        join(a, b, km, 60.0 * km / speed)


# --- water-only cells ---------------------------------------------------------
#
# A split base cell is replaced by all seven of its FINE_RES children, and the
# children of a coastal one include cells of open water: 146,962 of them on
# rebuild 34's graph. They inherit the base cell's land parts, so
# `severed_pairs` never cut them, and hex_edges joined them like any land cell.
# Where both shores of a water body belong to ONE land part -- the Gulf of
# Aqaba, whose Sinai and Hejaz coasts are both Afro-Eurasia -- a chain of them
# ran down the middle of the sea: Taba to Haql read 122 min over a road through
# the gulf, paying Egypt->Israel and Israel->Saudi Arabia on the way (the head
# cells are labelled Israel, graph/ground.PORT_ZONES), where the land route
# runs through Israel and Jordan and the sea route is a ferry. Same-part shores
# are the rule, not the exception -- every gulf, fjord, lagoon and big lake of
# a continent -- so this is judged by water, not by landmass.
#
# A cell is WATER when its hexagon touches no land polygon (`landmask`'s,
# lakes already cut out: driving across Natural Earth's lakes is as wrong as
# across the sea). Measured on a sample of 3,000: 6% hold land in OSM's
# coastline outside a Natural Earth lake, and the largest of those are river
# mouths OSM's sea polygons close off (the Amazon, the Tocantins, the
# Yangtze) -- water again. A water cell
#
#   * keeps its edges to the land neighbours of its NEAREST local shore only:
#     the land inside its neighbours' hexagons is split into its connected
#     pieces, and a neighbour counts when its hexagon meets the piece nearest
#     the water cell's centre -- so one water cell can no longer join the two
#     shores of a strait two cells wide;
#   * keeps no edge to another water cell, except, where it has no land
#     neighbour at all, ONE edge towards land: to a water neighbour one step
#     nearer (breadth-first from the cells that touch land). Each offshore
#     cell, ferry landing or airport on Natural Earth's water is then still
#     reached from exactly one shore, and no chain can carry a journey from
#     one shore to another;
#   * keeps every edge a fixed link or a road crossing passes along (`linked`):
#     a bridge's deck runs over water cells, and that is the one road there;
#   * keeps every edge an OSM motorway or trunk steps along (`road_hops`):
#     where one runs, Natural Earth's coast is wrong, not the road -- reclaimed
#     land on the Jiangsu coast, the approaches to the Pingtan bridge. A first
#     run without this cut 408 such hops in 349 ways. Minor roads are not read
#     (motorways.ways holds only these two classes), so a village street on
#     reclaimed land can still be cut: the limit, stated;
#   * keeps every land neighbour where a fixed link ENDS in it: the Ikema
#     Ohashi (Miyako) lands in a cell Natural Earth calls sea, and tied to
#     its nearest piece of land -- Ikema's -- the bridge led nowhere;
#   * never leans on a pair `severed_pairs` already cut: a water cell between
#     an island and the mainland stays with the shore that rule left it. A
#     first run without this stranded 3,194 cells (Aland, Lofoten, the Korean
#     and Dalmatian islands), each tied only to the island it was cut from.
#
# Measured on rebuild 34's graph (2026-10-17): 193,456 pairs cut, 0.47% of
# its edges; no motorway or trunk hop among them. Taba -> Haql goes from 122
# min over the gulf to 176 by Eilat and Aqaba; the bridges and ferries
# (Kerch, Oresund, Messina, the Causeway, King Fahd) read as before. 93 cells
# in 39 groups are no longer reached at all; bar two whose way in was a ferry
# the re-pricing could not tell from the hex edge, they are islets with no
# bridge, tunnel or ferry (Hart Island off the Bronx is one) -- the parts
# rule's own outcome. 2.6% of cells are later from Seoul, Cairo or Istanbul
# and 4.7% from Oslo, by 2-3 min at the median; the most are the far shores
# of Lake Onega, the Amazon and Tocantins mouths, the Patagonian and
# Norwegian fjords, and the coast of Guinea-Bissau.
WATER_CELLS_VERSION = 1


def water_cells_cached(bases: list[str], polygons: list) -> set[str]:
    """`water_cells`, cached in data/build: keyed on the land universe (the
    archives `landmask` reads and its own constants), the split base cells
    and WATER_CELLS_VERSION -- the geometry pass costs minutes, and every
    input that shapes it is in the key."""
    import hashlib

    from transport_maps.sources import landmask
    from transport_maps.sources._utils import _atomic_write, _params_hash

    if not bases:
        return set()
    split_hash = hashlib.sha256("".join(sorted(bases)).encode()).hexdigest()
    stamp = _params_hash(landmask._landmasses_cache_path(config.SOLVE_RES, landmask._sources()).name,
                         split_hash, config.FINE_RES, WATER_CELLS_VERSION)
    out = config.BUILD / f"water_cells_r{config.FINE_RES}_{stamp}.parquet"
    if out.exists():
        return set(pl.read_parquet(out)["cell"].to_list())
    found = water_cells(bases, polygons)
    config.ensure_dirs()
    _atomic_write(out, lambda tmp: pl.DataFrame({"cell": sorted(found)},
                                                schema={"cell": pl.Utf8}).write_parquet(tmp))
    return found


def water_cells(bases: list[str], polygons: list) -> set[str]:
    """The FINE_RES children of `bases` (split base cells) whose hexagon
    touches no polygon of `polygons` (the land parts).

    The tree holds the hexagons and the polygons are the queries: shapely
    prepares the query geometry, so each continent is prepared once rather
    than tested whole against every hexagon."""
    import numpy as np
    import shapely

    def hexagons(cells: list[str]):
        # One by one: a boundary has 6 vertices, 5 at a pentagon and up to
        # 10 where it crosses an icosahedron edge, so no single array holds them.
        return np.array([shapely.Polygon([(lo, la) for la, lo in h3.cell_to_boundary(c)])
                         for c in cells], dtype=object)

    _part, inside = shapely.STRtree(hexagons(bases)).query(polygons, predicate="contains")
    inland = set(inside.tolist())
    coastal = [b for i, b in enumerate(bases) if i not in inland]
    kids = [k for b in coastal for k in h3.cell_to_children(b, config.FINE_RES)]
    if not kids:
        return set()
    _part, touched = shapely.STRtree(hexagons(kids)).query(polygons, predicate="intersects")
    land = set(touched.tolist())
    return {k for i, k in enumerate(kids) if i not in land}


def _graph_neighbours(cell: str, cell_pos: dict[str, int]) -> list[str]:
    """The graph cells hex_edges joins `cell` (a FINE_RES cell) to: each ring
    neighbour that is a graph cell, else its unsplit base cell."""
    out = []
    for n in h3.grid_ring(cell, 1):
        if n in cell_pos:
            out.append(n)
        else:
            p = h3.cell_to_parent(n, config.SOLVE_RES)
            if p in cell_pos and p not in out:
                out.append(p)
    return out


def _tiles(polygons: list, max_coords: int = 512):
    """`polygons` cut into pieces of at most `max_coords` vertices, halving
    the longer side of the box each time: one continent intersected against
    each of a hundred thousand small areas would be read whole every time."""
    import numpy as np
    import shapely

    out, stack = [], [(g, g.bounds) for g in polygons]
    while stack:
        g, (x0, y0, x1, y1) = stack.pop()
        if shapely.get_num_coordinates(g) <= max_coords or max(x1 - x0, y1 - y0) < 1e-3:
            out.append(g)
            continue
        if x1 - x0 >= y1 - y0:
            xm = (x0 + x1) / 2
            halves = [(x0, y0, xm, y1), (xm, y0, x1, y1)]
        else:
            ym = (y0 + y1) / 2
            halves = [(x0, y0, x1, ym), (x0, ym, x1, y1)]
        for box in halves:
            piece = shapely.intersection(g, shapely.box(*box))
            if not piece.is_empty and piece.area > 0:
                stack.append((piece, box))
    return np.array(out, dtype=object)


def road_hops(ways: pl.DataFrame, water: set[str], cell_pos: dict[str, int],
              cell_index_at: Callable[[float, float], int | None]) -> set[tuple[int, int]]:
    """Ordered (u, v) graph-cell pairs a way of `ways` (lat/lon lists, as
    `motorways.ways` gives) steps directly between, at least one of them a
    `water` cell. A motorway or trunk is there, so the cell is not open water
    whatever Natural Earth's coast says: reclaimed land (Jiangsu, Fujian), a
    causeway's embankment, a bridge's approach tagged as plain road. Sampled
    as `motorways.motorway_mask` samples them; only the points near a water
    cell are looked up."""
    from transport_maps.sources import motorways

    if not water or ways.is_empty():
        return set()
    lens = ways["lat"].list.len().to_numpy()
    starts = np.r_[0, np.cumsum(lens)[:-1]].astype(np.int64)
    lat = ways["lat"].explode().to_numpy()
    lon = ways["lon"].explode().to_numpy()
    # Points in walking order: densify's interior points sort by node index
    # plus fraction, each segment's last node by its own index.
    ends = np.r_[starts[1:], len(lat)]
    seg = np.ones(len(lat), dtype=bool)
    seg[ends - 1] = False
    i = np.flatnonzero(seg)
    i = i[np.abs(lon[i + 1] - lon[i]) < 180.0]
    dy = (lat[i + 1] - lat[i]) * 111.0
    dx = (lon[i + 1] - lon[i]) * 111.0 * np.cos(np.radians(0.5 * (lat[i] + lat[i + 1])))
    n = np.maximum(1, np.ceil(np.hypot(dx, dy) / motorways.DENSIFY_KM).astype(np.int64))
    which = np.repeat(np.arange(len(i)), n)
    t = (np.arange(len(which)) - np.repeat(np.cumsum(n) - n, n)) / n[which]
    a = i[which]
    plat = np.r_[lat[a] + t * (lat[a + 1] - lat[a]), lat[i + 1]]
    plon = np.r_[lon[a] + t * (lon[a + 1] - lon[a]), lon[i + 1]]
    order_key = np.r_[a + t, (i + 1).astype(float)]
    way_of = np.repeat(np.arange(len(starts)), lens)[np.r_[a, i + 1]]
    # The 0.1-degree bins around each water cell (a res-7 cell is ~0.03).
    bins = set()
    for w in water:
        la, lo = h3.cell_to_latlng(w)
        r, c = math.floor(la * 10), math.floor(lo * 10)
        bins.update((r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))
    near = np.fromiter(((r, c) in bins for r, c in zip(np.floor(plat * 10).astype(np.int64).tolist(),
                                                       np.floor(plon * 10).astype(np.int64).tolist())),
                       dtype=bool, count=len(plat))
    # Keep a near point's way neighbours too, so the hop into the area counts.
    order = np.argsort(order_key, kind="stable")
    near_o = near[order]
    near_o = near_o | np.r_[near_o[1:], False] | np.r_[False, near_o[:-1]]
    ranks = np.flatnonzero(near_o)
    water_pos = {cell_pos[w] for w in water if w in cell_pos}
    pairs: set[tuple[int, int]] = set()
    prev, prev_rank, prev_way = None, -2, -1
    for r in ranks.tolist():
        k = order[r]
        here = cell_index_at(float(plat[k]), float(plon[k]))
        if (here is not None and prev is not None and here != prev and r == prev_rank + 1
                and way_of[k] == prev_way and (here in water_pos or prev in water_pos)):
            pairs.add((prev, here))
            pairs.add((here, prev))
        prev, prev_rank, prev_way = here, r, way_of[k]
    return pairs


def water_pairs(water: set[str], cell_pos: dict[str, int], linked: set[tuple[int, int]],
                polygons: list, severed: frozenset = frozenset(),
                landfalls: frozenset = frozenset()) -> frozenset[tuple[int, int]]:
    """Ordered (u, v) graph-cell pairs at a water cell that hex_edges must not
    join (see the block comment above). `severed` holds the pairs already cut
    (`severed_pairs`): a water cell between an island and the main shore is
    tied to the shore that rule left it, never to the one it cut.
    `landfalls` are the graph positions of cells a fixed link ends in: a
    bridge ends on land, so where its end falls in a water cell the coast is
    wrong there and the cell keeps every land neighbour."""
    import shapely

    tiles = _tiles(polygons)
    tree = shapely.STRtree(tiles)
    water = {w for w in water if w in cell_pos}
    keep: set[frozenset] = set()
    land_nb: dict[str, list[str]] = {}
    nbrs: dict[str, list[str]] = {}
    for w in water:
        nb = [n for n in _graph_neighbours(w, cell_pos)
              if (cell_pos[w], cell_pos[n]) not in severed]
        nbrs[w] = nb
        land_nb[w] = [n for n in nb if n not in water]

    def hexagon(c: str):
        return shapely.Polygon([(lo, la) for la, lo in h3.cell_to_boundary(c)])

    for w, lands in land_nb.items():
        if cell_pos[w] in landfalls:
            keep.update(frozenset((w, n)) for n in lands)
            continue
        if len(lands) == 1:
            keep.add(frozenset((w, lands[0])))
            continue
        if not lands:
            continue
        hexes = {n: hexagon(n) for n in lands}
        if any(hx.bounds[2] - hx.bounds[0] > 180 for hx in hexes.values()):
            # Across the antimeridian a hexagon in plain lon/lat wraps the
            # globe the long way; the few there (Fiji, Chukotka) keep every
            # land neighbour, as before.
            keep.update(frozenset((w, n)) for n in lands)
            continue
        area = shapely.union_all(list(hexes.values()))
        idx = tree.query(area, predicate="intersects")
        land = shapely.union_all(shapely.intersection(tiles[idx], area)) if len(idx) else None
        pieces = [] if land is None or land.is_empty else \
            [g for g in shapely.get_parts(land) if g.area > 0]
        if not pieces:
            keep.update(frozenset((w, n)) for n in lands)
            continue
        centre = shapely.Point(h3.cell_to_latlng(w)[::-1])
        near = min(pieces, key=lambda g: g.distance(centre))
        for n, hx in hexes.items():
            if hx.intersects(near) and shapely.intersection(hx, near).area > 0:
                keep.add(frozenset((w, n)))

    # Offshore water: one edge each, towards land, breadth-first.
    level = {w for w, lands in land_nb.items() if lands}
    seen = set(level)
    while level:
        nxt = set()
        for w in level:
            for n in nbrs[w]:
                if n in water and n not in seen:
                    keep.add(frozenset((n, w)))
                    seen.add(n)
                    nxt.add(n)
        level = nxt

    out: set[tuple[int, int]] = set()
    for w in water:
        u = cell_pos[w]
        for n in nbrs[w]:
            v = cell_pos[n]
            if frozenset((w, n)) in keep or (u, v) in linked or (v, u) in linked:
                continue
            out.add((u, v))
            out.add((v, u))
    return frozenset(out)
