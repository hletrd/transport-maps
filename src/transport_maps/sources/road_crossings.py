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

Of a tracked stretch of road only the steps that can join something are kept
(`_step_matters`): one between cells on disjoint land parts, one inside or
into a cell that touches two parts (its children are judged one by one later,
graph/landmass.fine_cell_parts), and one onto a cell off the land mask, which
graph/landmass.spanning_links turns into a span when it reaches land again.
The rows have the fixed-link SCHEMA with kind "road", so linked_pairs and
spanning_links read them as they read a bridge.

Refused, as fixed_links refuses a footbridge: highways that are not roads
(footways, paths, cycleways -- `ROAD_HIGHWAYS` is the GRIP classes the spans
are costed at), ice and winter roads (a strait is not driven for most of the
year), and a way that is also a ferry route (a sailing mapped as a road).

Not read, stated rather than hidden: a road step whose two nodes are both
outside the seams' vicinity, and so a single straight step longer than
SEAM_RING rings that jumps a strait. And a causeway longer than SEAM_RING
rings of open water from either shore: there the shores are not seams at all.
"""

from __future__ import annotations

import itertools
import logging
import math
import pathlib
from dataclasses import dataclass

import h3
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
# A step longer than this is sampled, so a cell it passes through between its
# two nodes is seen. A FINE_RES edge is about 1.4 km.
SAMPLE_KM = 0.5
# Coarse bins over the vicinity, a fast reject before the H3 lookup of each of
# hundreds of millions of road nodes; 0.5 degrees is several cells wide.
BIN_DEG = 0.5

# Bumped when the parse changes shape.
ROAD_CROSSING_PARSER_VERSION = 1

STEM = "road_crossings"


@dataclass(frozen=True)
class Seams:
    """Where road nodes are read: SOLVE_RES cells as H3 integers."""

    parts: dict[int, frozenset[int]]   # every land cell of the vicinity -> its land parts
    vicinity: frozenset[int]           # tracked cells, land or water
    bins: frozenset[int]               # `_bin` of everything in the vicinity


def _bin(lat: float, lon: float) -> int:
    return int((lat + 90.0) / BIN_DEG) * 1000 + int((lon + 180.0) / BIN_DEG)


def seams(cells: list[str], parts: list[tuple[int, ...]]) -> Seams:
    """The seams of the land universe `cells`, whose land parts are `parts`
    (landmask.land_cell_landmasses order). The pole cells touch no part, carry
    no evidence of water (graph/landmass never severs them) and are never a
    seam, nor make one of a neighbour."""
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
    return Seams({c: land[c] for c in vicinity if c in land}, frozenset(vicinity), frozenset(bins))


def _is_road(tags) -> str | None:
    """The highway value when this way is a year-round road, else None."""
    highway = tags.get("highway")
    if highway not in ROAD_HIGHWAYS:
        return None
    if any(tags.get(k) == "yes" for k in SEASONAL) or tags.get("route") == "ferry":
        return None
    return highway


def _step_matters(a: tuple[float, float], b: tuple[float, float], s: Seams) -> bool:
    """Whether the road step a -> b can join two cells severing would cut."""
    from h3.api import basic_int as h3i

    km = _km(a, b)
    n = max(1, math.ceil(km / SAMPLE_KM))
    prev = None
    for k in range(n + 1):
        t = k / n
        c = h3i.latlng_to_cell(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                               config.SOLVE_RES)
        if c == prev:
            continue
        if c in s.vicinity:
            p = s.parts.get(c)
            if p is None or len(p) > 1:
                return True                # off the land mask, or straddling two parts
            q = s.parts.get(prev) if prev is not None else None
            if q is not None and not p & q:
                return True                # from one land part straight onto another
        prev = c
    return False


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle km between two (lat, lon) points."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, h)))


def _runs(pts: list[tuple[float, float] | None], s: Seams) -> list[list[tuple[float, float]]]:
    """The stretches of one way worth keeping: maximal runs of consecutive
    steps that matter. `None` is a node outside the seams' vicinity, whose
    location was never kept; a step to or from it is not read."""
    out: list[list[tuple[float, float]]] = []
    run: list[tuple[float, float]] = []
    for a, b in itertools.pairwise(pts):
        if a is not None and b is not None and abs(b[1] - a[1]) <= 180.0 \
                and _step_matters(a, b, s):
            if not run:
                run = [a]
            run.append(b)
            continue
        if run:
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


def _crossings(path: pathlib.Path, s: Seams) -> list[dict]:
    """Every road stretch in one extract that can join two land parts.

    Three passes, the filtering in C++ wherever osmium offers it: road ways,
    recording their node ids; those nodes, keeping the location of the ones
    in the seams' vicinity; and the road ways again, only those touching a
    kept node, cut into the stretches `_runs` keeps.
    """
    from h3.api import basic_int as h3i

    road_filter = osmium.filter.TagFilter(*[("highway", h) for h in sorted(ROAD_HIGHWAYS)])
    on_roads = osmium.IdTracker()
    for way in osmium.FileProcessor(str(path), osmium.osm.WAY).with_filter(road_filter):
        if _is_road(way.tags):
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
    rows = []
    road_filter = osmium.filter.TagFilter(*[("highway", h) for h in sorted(ROAD_HIGHWAYS)])
    for way in (osmium.FileProcessor(str(path), osmium.osm.WAY)
                .with_filter(road_filter).with_filter(kept.contains_filter())):
        highway = _is_road(way.tags)
        if highway is None:
            continue
        pts = []
        for n in way.nodes:
            if n.ref in known:
                loc = where.get(n.ref)
                pts.append((loc.lat, loc.lon))
            else:
                pts.append(None)
        for run in _runs(pts, s):
            # The fixed-link rule: a stretch inside one fine cell joins nothing.
            if len({h3.latlng_to_cell(la, lo, fixed_links.KEEP_RES) for la, lo in run}) < 2:
                continue
            rows.append({"way_id": way.id, "kind": "road", "highway": highway,
                         "name": way.tags.get("name") or "",
                         "lat": [p[0] for p in run], "lon": [p[1] for p in run]})
    return rows


def _landmass_key() -> str:
    """The land parts the seams were drawn from: the landmass cache's own
    stamp, which carries the land universe and its archives (G2)."""
    return landmask._landmasses_cache_path(config.SOLVE_RES, landmask._sources()).name


def _params_key() -> str:
    """Every constant that governs the parquet's content, and the land parts:
    the seams move with them, so a new coast is a new parse."""
    return _params_hash(sorted(ROAD_HIGHWAYS), sorted(SEASONAL), SEAM_RING, SAMPLE_KM,
                        BIN_DEG, fixed_links.KEEP_RES,
                        sorted((k, str(v)) for k, v in fixed_links.SCHEMA.items()),
                        ROAD_CROSSING_PARSER_VERSION, _landmass_key())


def _cache_path(region: str, source_key: str) -> pathlib.Path:
    return fixed_links._cache_path(region, source_key, stem=STEM, params=_params_key())


def road_crossings(*, extracts_dir: pathlib.Path | None = None) -> pl.DataFrame | None:
    """Every road stretch across a land-part seam, across all REGIONS, in the
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
    found: Seams | None = None
    for region, source in sources.items():
        if source.suffix == ".parquet":
            frames.append(pl.read_parquet(source))
            continue
        if found is None:
            found = seams(landmask.land_cells(config.SOLVE_RES),
                          landmask.land_cell_landmasses(config.SOLVE_RES))
        logger.info("parsing road crossings from %s (%.1f GB)", source.name,
                    source.stat().st_size / 1e9)
        df = pl.DataFrame(_crossings(source, found), schema=fixed_links.SCHEMA)
        _atomic_write(_cache_path(region, fixed_links._source_key(source)),
                      lambda tmp, df=df: df.write_parquet(tmp))
        frames.append(df)
    # A stretch near a continental boundary is in two extracts under one id.
    return pl.concat(frames).unique(subset=["way_id", "lat", "lon"], maintain_order=True)
