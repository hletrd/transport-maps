"""Roads that cross from one land part to another on neither a bridge nor a tunnel.

graph/landmass severs two adjacent land cells on different Natural Earth land
parts unless a fixed link passes between them, and sources/fixed_links reads
only ways tagged `bridge` or `tunnel`. A road built on fill carries neither
tag, and that is how much of the world's coast is joined: a seawall, a polder
dike, a causeway, the untagged stretch across an islet between two bridge
decks, reclaimed land Natural Earth's 1:10M coast predates. Measured on
rebuild 27's index (plan/2026-10-02-rebuild28-model.md, A16): Daebu-do,
Seonjae-do and Yeongheung-do -- joined to Siheung by the Sihwa seawall, a
12.7 km primary road whose only bridge is a short deck at the tidal plant --
read "no route" from every origin; so did Jido, Jeungdo and Imjado, joined by
polder roads; and Apdo was reached from Mokpo only by ferry, because each deck
of the Apdo Bridge lies inside one fine cell and the cell boundary falls on the
untagged road across the islet between them.

OSM records such a road as plainly as a bridge: it is there. What it costs is
the geometry. The bridge parse reads a few hundred thousand ways; Europe's
roads are tens of millions of ways and some 600 million node references, and
no node-location index this machine can hold beside a build would keep them.
So the parse reads every road's node list but keeps locations only on the
SEAMS, the only places a crossing can matter:

  * a land cell is a seam when its hexagon touches two land parts, or a land
    cell within SEAM_RING rings of it lies on a land part it does not touch --
    every pair severed_pairs can cut is between two such cells, and the water
    a causeway runs over is within SEAM_RING rings of them;
  * a road node is tracked when its SOLVE_RES cell, land or water, is within
    SEAM_RING rings of a seam cell.

A crossing is then judged by the ROAD and the land under it, not by the cells
it passes (`_crossing_edges`). Every tracked node is placed on the land part
whose polygon holds it at least COAST_MARGIN_DEG inside its coast, or on
water. A road step from one part straight onto another is a crossing; so is a
stretch of road over water -- however many ways OSM cuts it into, the Sihwa
seawall is a dozen -- that reaches land on two parts. Three versions were
measured and dropped first, all on Asia:

  * judging by the cells' land-part labels kept 29,680 "crossings", most of
    them coastal roads through a strait cell Natural Earth's coarse coast puts
    on the far shore -- a road on Bali's west coast "reached" Java -- and
    joined Bali, Chiloe, Guimaras and K'gari, which only ferries reach;
  * judging way by way kept 62 and joined none of Daebu-do, Jido or Apdo: no
    single way of the seawall runs from land to land;
  * judging by the land right up to the coast joined Buton to Muna and
    Adonara to Flores, through Natural Earth slivers a few dozen metres deep
    on the wrong shore (COAST_MARGIN_DEG).

The rows have the fixed-link SCHEMA with kind "road", one per run of crossing
steps along a way, so linked_pairs and spanning_links read them as they read
a bridge and stitch the ways back together by their shared nodes.

Refused, as fixed_links refuses a footbridge: highways that are not roads
(footways, paths, cycleways -- `ROAD_HIGHWAYS` is the GRIP classes the spans
are costed at), ice and winter roads (a strait is not driven for most of the
year), and a way that is also a ferry route (a sailing mapped as a road).

Not read, stated rather than hidden: a road step with a node outside the
seams' vicinity, so a single straight step longer than SEAM_RING rings that
jumps a strait; and a causeway with more than SEAM_RING rings of open water
on either side, whose shores are not seams at all.
"""

from __future__ import annotations

import itertools
import logging
import pathlib
from array import array
from dataclasses import dataclass

import numpy as np
import osmium
import polars as pl

from .. import config
from . import fixed_links, landmask
from ._utils import _atomic_write, _params_hash

logger = logging.getLogger(__name__)

# The highway values a crossing is read for: exactly the keys of
# graph/landmass.SPAN_ROAD_CLASS (tests/sources/test_road_crossings.py holds
# the two together), so a stretch over water is costed at a FITTED road speed
# and a footway across a strait is never a road.
ROAD_HIGHWAYS = frozenset({
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
    "unclassified", "residential", "road", "service", "living_street",
})
# Tags (with value "yes") under which a road across water is no year-round road.
SEASONAL = frozenset({"ice_road", "winter_road"})
# How far from a land-part boundary roads are read, in SOLVE_RES rings (about
# 7 km each). Two rings take in the Sihwa seawall from both shores.
SEAM_RING = 2
# Coarse bins over the vicinity, a fast reject before the H3 lookup of each of
# hundreds of millions of road nodes; 0.5 degrees is several cells wide.
BIN_DEG = 0.5
# Natural Earth's 1:10M coast is generalised, and across a strait a few
# kilometres wide its polygons can reach onto the other shore. A road node this
# close inside a part's coast is not trusted to be on it and counts as water:
# only land this far in says which part a road is on. Measured on Asia's road
# steps (2026-10-04): with no margin, Baubau's streets on Buton "reached" Muna
# through two Natural Earth islets 19 and 52 m deep, and Adonara joined Flores;
# at 0.005 degrees (about 550 m) neither does, and every named case in
# scripts/check_fixed_links.py holds. 1,609 of the 6,985 parts are narrower
# than twice this: no road crossing reaches them, and they stay as cut as they
# were before road crossings were read.
COAST_MARGIN_DEG = 0.005
# Marks a node on no land part.
WATER = -(2 ** 31)

# Bumped when the parse changes shape.
# 3: a crossing is judged by the land parts under the road's nodes, across
#    every way it runs along (the module docstring has the two before).
# 4: and only by land COAST_MARGIN_DEG inside a part.
ROAD_CROSSING_PARSER_VERSION = 4

STEM = "road_crossings"


@dataclass(frozen=True)
class Seams:
    """Where road nodes are read: SOLVE_RES cells as H3 integers."""

    vicinity: frozenset[int]           # tracked cells, land or water
    bins: frozenset[int]               # `_bin` of everything in the vicinity


def _bin(lat: float, lon: float) -> int:
    return int((lat + 90.0) / BIN_DEG) * 1000 + int((lon + 180.0) / BIN_DEG)


def seams(cells: list[str], parts: list[tuple[int, ...]]) -> Seams:
    """The seams of the land universe `cells`, whose land parts are `parts`
    (landmask.land_cell_landmasses order). The pole cells touch no part, carry
    no evidence of water (graph/landmass never severs them) and are never a
    seam, nor make one of a neighbour."""
    import h3
    from h3.api import basic_int as h3i

    land = {h3.str_to_int(c): frozenset(p) for c, p in zip(cells, parts)}
    seam: set[int] = set()
    for c, p in land.items():
        if not p:
            continue
        if len(p) > 1:
            seam.add(c)
            continue
        for n in h3i.grid_disk(c, SEAM_RING):
            q = land.get(n)
            if q and not p & q:
                seam.add(c)
                break
    vicinity: set[int] = set()
    for c in seam:
        vicinity.update(h3i.grid_disk(c, SEAM_RING))
    bins: set[int] = set()
    for c in vicinity:
        la, lo = h3i.cell_to_latlng(c)
        for dla in (-BIN_DEG, 0.0, BIN_DEG):
            for dlo in (-BIN_DEG, 0.0, BIN_DEG):
                bins.add(_bin(max(-89.99, min(89.99, la + dla)), (lo + dlo + 180.0) % 360.0 - 180.0))
    return Seams(frozenset(vicinity), frozenset(bins))


class LandParts:
    """Which land part a point lies on: the polygons
    landmask.land_cell_landmasses numbers, by the same ids; WATER on none, and
    on the outer `margin` degrees of every part (COAST_MARGIN_DEG)."""

    def __init__(self, polygons: list[tuple[int, object]], margin: float = 0.0):
        import shapely

        shrunk = shapely.buffer([p for _, p in polygons], -margin) if margin else \
            [p for _, p in polygons]
        kept = [(i, p) for (i, _), p in zip(polygons, shrunk) if not p.is_empty]
        self._ids = [i for i, _ in kept]
        self._polys = [p for _, p in kept]
        for poly in self._polys:
            shapely.prepare(poly)
        self._tree = shapely.STRtree(self._polys)

    @classmethod
    def natural_earth(cls) -> LandParts:
        """Antarctica's wedges are one landmass, as they are there."""
        return cls([(landmask.ANTARCTICA_LANDMASS if p.bounds[3] <= landmask.ANTARCTICA_MAX_LAT
                     else i, p) for i, p in enumerate(landmask._land_parts())],
                   margin=COAST_MARGIN_DEG)

    def __call__(self, lats, lons) -> np.ndarray:
        import shapely

        xs, ys = np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)
        out = np.full(len(xs), WATER, dtype=np.int64)
        if not len(xs):
            return out
        at, poly = self._tree.query(shapely.points(xs, ys))      # bounding boxes only
        for j in np.unique(poly):
            near = at[poly == j]
            # Parts do not overlap, so a point is on at most one.
            out[near[shapely.contains_xy(self._polys[j], xs[near], ys[near])]] = self._ids[j]
        return out


def _crossing_edges(a: np.ndarray, b: np.ndarray, part: np.ndarray) -> np.ndarray:
    """Which road steps belong to a crossing, as a mask over the steps a -> b.

    `a` and `b` index nodes and `part` is each node's land part (WATER on
    none). A step from one part straight onto another is a crossing. A step
    on or onto water belongs to a crossing when the stretch of water-borne
    road it is part of -- the steps between water nodes, joined through every
    way that shares a node -- reaches land on two different parts.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    pa, pb = part[a], part[b]
    direct = (pa != WATER) & (pb != WATER) & (pa != pb)
    wet = (pa == WATER) & (pb == WATER)
    n = len(part)
    _, comp = connected_components(
        coo_matrix((np.ones(int(wet.sum()), dtype=np.int8), (a[wet], b[wet])), shape=(n, n)),
        directed=False)
    # Where each stretch of water-borne road lands: (its component, the part).
    shore = (pa == WATER) != (pb == WATER)
    wet_end = np.where(pa[shore] == WATER, a[shore], b[shore])
    land_part = np.where(pa[shore] == WATER, pb[shore], pa[shore])
    landings = np.unique(np.stack([comp[wet_end], land_part], axis=1), axis=0)
    comps, n_parts = np.unique(landings[:, 0], return_counts=True)
    crossing = np.zeros(n, dtype=bool)
    crossing[comps[n_parts >= 2]] = True
    touches = (wet | shore) & crossing[comp[np.where(pa == WATER, a, b)]]
    return direct | touches


def _runs(refs: list[int], marked: set[tuple[int, int]]) -> list[list[int]]:
    """A way's maximal runs of consecutive marked steps, as node ids. Every
    step was recorded in the order its own way takes it, so a step is looked
    up the same way round."""
    out: list[list[int]] = []
    run: list[int] = []
    for x, y in itertools.pairwise(refs):
        if (x, y) in marked:
            if not run:
                run = [x]
            run.append(y)
        elif run:
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


def _is_road(tags) -> str | None:
    """The highway value when this way is a year-round road, else None."""
    highway = tags.get("highway")
    if highway not in ROAD_HIGHWAYS:
        return None
    if any(tags.get(k) == "yes" for k in SEASONAL) or tags.get("route") == "ferry":
        return None
    return highway


def _roads(path: pathlib.Path, tracker: osmium.IdTracker | None = None):
    """Road ways in one extract -- only those touching `tracker`'s nodes, if given."""
    fp = osmium.FileProcessor(str(path), osmium.osm.WAY).with_filter(
        osmium.filter.TagFilter(*[("highway", h) for h in sorted(ROAD_HIGHWAYS)]))
    if tracker is not None:
        fp = fp.with_filter(tracker.contains_filter())
    for way in fp:
        highway = _is_road(way.tags)
        if highway is not None:
            yield way, highway


def _crossings(path: pathlib.Path, s: Seams, land: LandParts) -> list[dict]:
    """Every run of road in one extract that belongs to a land-part crossing.

    Four passes, the filtering in C++ wherever osmium offers it: road ways,
    recording their node ids; those nodes, keeping the location of the ones
    in the seams' vicinity; the road ways touching a kept node, recording the
    steps between two kept nodes; and those ways again, cut into the runs of
    steps `_crossing_edges` marks.
    """
    from h3.api import basic_int as h3i

    on_roads = osmium.IdTracker()
    for way, _ in _roads(path):
        on_roads.add_references(way)

    kept = osmium.IdTracker()
    where = osmium.index.create_map("sparse_mem_array")
    for node in osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(on_roads.id_filter()):
        loc = node.location
        if not loc.valid():
            continue
        lat, lon = loc.lat, loc.lon
        if _bin(lat, lon) in s.bins and h3i.latlng_to_cell(lat, lon, config.SOLVE_RES) in s.vicinity:
            kept.add_node(node.id)
            where.set(node.id, loc)
    del on_roads

    known = kept.node_ids()
    step_a, step_b = array("q"), array("q")
    for way, _ in _roads(path, kept):
        refs = [n.ref for n in way.nodes]
        for x, y in itertools.pairwise(refs):
            if x != y and x in known and y in known:
                step_a.append(x)
                step_b.append(y)
    if not step_a:
        return []
    ids, inverse = np.unique(np.concatenate([np.frombuffer(step_a, dtype=np.int64),
                                             np.frombuffer(step_b, dtype=np.int64)]),
                             return_inverse=True)
    locs = [where.get(int(i)) for i in ids]
    lat = np.array([loc.lat for loc in locs])
    lon = np.array([loc.lon for loc in locs])
    a, b = inverse[:len(step_a)], inverse[len(step_a):]
    # A step across the antimeridian would be interpolated the long way round.
    near = np.abs(lon[a] - lon[b]) <= 180.0
    marked_mask = _crossing_edges(a[near], b[near], land(lat, lon))
    marked = {(int(ids[x]), int(ids[y])) for x, y in zip(a[near][marked_mask], b[near][marked_mask])}
    if not marked:
        return []

    rows = []
    for way, highway in _roads(path, kept):
        for run in _runs([n.ref for n in way.nodes], marked):
            pts = [where.get(r) for r in run]
            rows.append({"way_id": way.id, "kind": "road", "highway": highway,
                         "name": way.tags.get("name") or "",
                         "lat": [p.lat for p in pts], "lon": [p.lon for p in pts]})
    return rows


def _landmass_key() -> str:
    """The land parts the seams and crossings were judged by: the landmass
    cache's own stamp, which carries the land universe and its archives (G2)."""
    return landmask._landmasses_cache_path(config.SOLVE_RES, landmask._sources()).name


def _params_key() -> str:
    """Every constant that governs the parquet's content, and the land parts:
    the seams and the crossings move with them, so a new coast is a new parse."""
    return _params_hash(sorted(ROAD_HIGHWAYS), sorted(SEASONAL), SEAM_RING, BIN_DEG,
                        COAST_MARGIN_DEG,
                        sorted((k, str(v)) for k, v in fixed_links.SCHEMA.items()),
                        ROAD_CROSSING_PARSER_VERSION, _landmass_key())


def _cache_path(region: str, source_key: str) -> pathlib.Path:
    return fixed_links._cache_path(region, source_key, stem=STEM, params=_params_key())


def road_crossings(*, extracts_dir: pathlib.Path | None = None) -> pl.DataFrame | None:
    """Every road run across a land-part seam, across all REGIONS, in the
    fixed-link SCHEMA with kind "road".

    None -- and says why -- when ANY region has neither a parse nor a raw
    extract. The caller then severs on bridges and tunnels alone, which is
    how every build before this one severed: the causeways are cut again, but
    nothing new is.
    """
    extracts_dir = extracts_dir or (config.CACHE / "osm")
    params = _params_key()
    sources = {region: fixed_links._source(region, extracts_dir, stem=STEM, params=params)
               for region in fixed_links.REGIONS}
    missing = [r for r, src in sources.items() if src is None]
    if missing:
        logger.warning("road-crossing data missing for %s; run scripts/osm_fixed_links.sh. "
                       "Land parts are joined by bridges and tunnels only, and causeways "
                       "stay cut.", ", ".join(missing))
        return None
    frames = []
    found: tuple[Seams, LandParts] | None = None
    for region, source in sources.items():
        if source.suffix == ".parquet":
            frames.append(pl.read_parquet(source))
            continue
        if found is None:
            found = (seams(landmask.land_cells(config.SOLVE_RES),
                           landmask.land_cell_landmasses(config.SOLVE_RES)),
                     LandParts.natural_earth())
        logger.info("parsing road crossings from %s (%.1f GB)", source.name,
                    source.stat().st_size / 1e9)
        df = pl.DataFrame(_crossings(source, *found), schema=fixed_links.SCHEMA)
        _atomic_write(_cache_path(region, fixed_links._source_key(source)),
                      lambda tmp, df=df: df.write_parquet(tmp))
        frames.append(df)
    # A run near a continental boundary is in two extracts under one id.
    return pl.concat(frames).unique(subset=["way_id", "lat", "lon"], maintain_order=True)
