"""Bridges and tunnels: the fixed links that carry a road or a railway over water.

`graph/ground.hex_edges` joins every pair of adjacent land cells, and a cell is
land when it touches any land at all (`landmask.land_cells` polyfills with
"overlap"). At SOLVE_RES a cell is about 7.4 km across, so two cells on
opposite shores of a narrower strait are H3 neighbours, and the graph drove
across the sea: Saipan to Tinian, over 8 km of open water, booked as 7.1
minutes of "major road".

Whether a strait can be crossed on land is a fact about the world, not about
geometry. Six geometric rules were measured against named bridges and named
ferry-only crossings and all six failed -- cutting the Oresund bridge,
splitting the Seto Inland Sea, or cutting nothing at all
(`plan/2026-09-17-phantom-land-links.md`). OpenStreetMap records the fact
directly: a way tagged `bridge` or `tunnel` that carries a highway or railway.

The `*-rail.osm.pbf` extracts cannot answer it. `scripts/osm_rail.sh` keeps
rail and ferries only, so they hold no highways at all. This reads the full
regional extracts that `scripts/osm_fixed_links.sh` downloads.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import datetime

import h3
import osmium
import polars as pl

from .. import config
from ._utils import _atomic_write, _params_hash

logger = logging.getLogger(__name__)

# Geofabrik's continental extracts, whose union covers every inhabited
# landmass. Geofabrik's index lists `russia` as a top-level region of its own,
# but the europe and asia extracts overlap it: the rail parse reads these same
# seven and holds 10,687 stops around Moscow and 362 around Vladivostok.
# Antarctica is omitted on purpose -- graph/landmass treats it as one landmass,
# so nothing there is ever severed and no bridge is needed to rejoin it.
REGIONS = ("africa", "asia", "australia-oceania", "central-america",
           "europe", "north-america", "south-america")

# `bridge`/`tunnel` values that mean there is none.
_ABSENT = frozenset({"no"})
# Life-cycle states in which the way is on the map but carries nothing.
_NOT_BUILT = frozenset({"proposed", "construction", "abandoned", "disused",
                        "razed", "dismantled"})

# A link is kept only when its nodes fall in more than one KEEP_RES cell. Every
# graph cell is at SOLVE_RES or at the finer FINE_RES, and an H3 cell is convex,
# so a polyline whose every node sits inside one FINE_RES cell never leaves it:
# it cannot join two graph cells. Most of the world's bridges are like that.
KEEP_RES = config.FINE_RES

SCHEMA = {"way_id": pl.Int64, "kind": pl.Utf8, "highway": pl.Utf8, "name": pl.Utf8,
          "lat": pl.List(pl.Float64), "lon": pl.List(pl.Float64)}

# Bumped when the parse changes shape, so a parquet written by old code is a
# MISS and not a silently reused wrong answer.
# 2: the `highway` value is kept, so graph/landmass can cost a link that spans
#    open water at its road class, and refuse a footbridge as a road.
FIXED_LINK_PARSER_VERSION = 2


def carries_traffic(tags) -> str | None:
    """"highway" or "railway" when this way is a bridge or tunnel that carries
    one, else None.

    `bridge=no` and `tunnel=no` are explicit denials and count as absent. A way
    still in a planned or ruined life-cycle state carries nothing today.
    """
    if tags.get("bridge", "no") in _ABSENT and tags.get("tunnel", "no") in _ABSENT:
        return None
    highway = tags.get("highway")
    if highway and highway not in _NOT_BUILT:
        return "highway"
    railway = tags.get("railway")
    if railway and railway not in _NOT_BUILT:
        return "railway"
    return None


def _links(path: pathlib.Path) -> list[dict]:
    """Every fixed link in one extract whose nodes span more than one KEEP_RES cell.

    Two passes, both filtered in C++ before anything reaches Python: ways that
    carry a `bridge` or `tunnel` key, then only the nodes those ways reference.
    A pure-Python pass over the 15 GB Asia extract took 41 minutes, almost all
    of it in callbacks for objects that were then thrown away.
    """
    ways: dict[int, tuple[list[int], str, str, str]] = {}
    wanted: set[int] = set()
    fp = osmium.FileProcessor(str(path), osmium.osm.WAY).with_filter(
        osmium.filter.KeyFilter("bridge", "tunnel"))
    for way in fp:
        kind = carries_traffic(way.tags)
        if kind is None:
            continue
        refs = [n.ref for n in way.nodes]
        if len(refs) < 2:
            continue
        ways[way.id] = (refs, kind, way.tags.get("highway") or "", way.tags.get("name") or "")
        wanted.update(refs)

    coords: dict[int, tuple[float, float]] = {}
    if wanted:
        fp = osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(
            osmium.filter.IdFilter(wanted))
        for node in fp:
            if node.location.valid():
                coords[node.id] = (node.location.lat, node.location.lon)

    rows = []
    for way_id, (refs, kind, highway, name) in ways.items():
        pts = [coords[r] for r in refs if r in coords]
        if len(pts) < 2:
            continue
        if len({h3.latlng_to_cell(lat, lon, KEEP_RES) for lat, lon in pts}) < 2:
            continue
        rows.append({"way_id": way_id, "kind": kind, "highway": highway, "name": name,
                     "lat": [p[0] for p in pts], "lon": [p[1] for p in pts]})
    return rows


def _params_key() -> str:
    """Every constant that governs the parquet's content."""
    return _params_hash(sorted(_ABSENT), sorted(_NOT_BUILT), KEEP_RES,
                        sorted((k, str(v)) for k, v in SCHEMA.items()),
                        FIXED_LINK_PARSER_VERSION)


def _mtime_key(raw: pathlib.Path) -> str:
    """The pre-G2 identity of an extract: its name, size and mtime. Still the
    key for an extract whose header carries no snapshot."""
    st = raw.stat()
    return _params_hash(raw.name, st.st_size, st.st_mtime_ns)


def _source_key(raw: pathlib.Path) -> str:
    """The extract's identity: the replication snapshot in its header, with
    its name and size (G2). The snapshot leads the key, readable, so a cache
    still says which snapshot it was parsed from once the 70 GB of raw
    extracts are gone -- which is what the freshness check reads then
    (`cached_snapshot`). An mtime said only when the file was last touched."""
    from transport_maps.sources import geofabrik

    snap = geofabrik.snapshot(raw)
    if snap is None:
        return _mtime_key(raw)
    return (f"{geofabrik.stamp(snap)}-"
            f"{_params_hash(raw.name, raw.stat().st_size, snap.isoformat())}")


def _snapshot_of(cache: pathlib.Path) -> datetime | None:
    """The snapshot a cache's name records, if its key leads with one."""
    from datetime import UTC

    head = cache.stem.rsplit("_", 1)[-1].split("-", 1)[0]
    try:
        return datetime.strptime(head, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def cached_snapshot(region: str) -> datetime | None:
    """The newest snapshot any cache under the current parser constants was
    parsed from; None when none records one."""
    snaps = [s for p in config.CACHE.glob(f"fixed_links_{region}_{_params_key()}_*.parquet")
             if (s := _snapshot_of(p)) is not None]
    return max(snaps, default=None)


def _cache_path(region: str, source_key: str) -> pathlib.Path:
    # Underscore-separated so the stamp is its own field; region names carry
    # hyphens ("north-america") and never an underscore.
    return config.CACHE / f"fixed_links_{region}_{_params_key()}_{source_key}.parquet"


def _source(region: str, extracts_dir: pathlib.Path) -> pathlib.Path | None:
    """Where one region's links will come from -- a parquet to read, or a raw
    extract to parse into one -- or None when there is neither.

    The cache is keyed on the parser constants AND on the extract it was read
    from. The raw extracts are 70 GB between them and exist only to feed this
    parse, so a cache must stay usable once they are deleted: with the raw file
    present the exact source key must match (a newer download is a MISS); with
    it absent, the newest cache under the current parser constants is used.
    """
    raw = extracts_dir / f"{region}.osm.pbf"
    if raw.exists():
        from transport_maps.sources import geofabrik

        cached = _cache_path(region, _source_key(raw))
        geofabrik.adopt(cached, _cache_path(region, _mtime_key(raw)))
        return cached if cached.exists() else raw
    # The newest snapshot first; mtime only among caches that record none.
    found = sorted(config.CACHE.glob(f"fixed_links_{region}_{_params_key()}_*.parquet"),
                   key=lambda p: (_snapshot_of(p) is not None,
                                  _snapshot_of(p) or datetime.min, p.stat().st_mtime))
    return found[-1] if found else None


def _load(region: str, source: pathlib.Path) -> pl.DataFrame:
    if source.suffix == ".parquet":
        return pl.read_parquet(source)
    logger.info("parsing fixed links from %s (%.1f GB)", source.name, source.stat().st_size / 1e9)
    df = pl.DataFrame(_links(source), schema=SCHEMA)
    _atomic_write(_cache_path(region, _source_key(source)), lambda tmp: df.write_parquet(tmp))
    return df


def fixed_links(*, extracts_dir: pathlib.Path | None = None) -> pl.DataFrame | None:
    """Every fixed link that can join two graph cells, across all REGIONS.

    Returns None -- and says why -- when ANY region is missing. Severing land
    cells uses the absence of a link as evidence of water, so a region with no
    link data would lose every bridge it has: a partial set is worse than none.

    Coverage is settled BEFORE anything is parsed. Parsing as it went, one
    missing region would be discovered only after hours spent on the others,
    and the result thrown away.
    """
    extracts_dir = extracts_dir or (config.CACHE / "osm")
    sources = {region: _source(region, extracts_dir) for region in REGIONS}
    missing = [r for r, s in sources.items() if s is None]
    if missing:
        logger.warning("fixed-link data missing for %s; run scripts/osm_fixed_links.sh. "
                       "Adjacent land cells stay joined across water, as before.",
                       ", ".join(missing))
        return None
    frames = [_load(region, source) for region, source in sources.items()]
    # A link near a continental boundary is in two extracts under one id.
    return pl.concat(frames).unique(subset=["way_id"], keep="first")
