"""Which land cells an OSM motorway or expressway crosses.

GRIP4 grades every road of its "highways" type alike, so a six-lane
expressway and an ordinary two-lane national highway get one speed. In a
lower-middle-income country, where the fitted speed for that grade is
59 km/h, the Cairo -> Alexandria desert road and the Yamuna Expressway were
priced like the old roads beside them (rebuild 31: 252 min of ground against
Google's 151, and 283 against 204). OSM says which roads are motorways, so a
cell one crosses gets graph/ground.MOTORWAY_CLASS, with its own fitted speed.

Input: the {region}-roads.osm.pbf extracts scripts/osm_roads.sh filters from
the full continental extracts (highway=motorway and highway=trunk ways, all
tags, their nodes). Two derived caches, each keyed on its constants and
inputs: the ways (`ways`), and the cells a given index's ways cross
(`motorway_mask`).

Which trunk roads count is RULE: a structure chosen out of fold with the
road speeds (scripts/calibrate_ground.py; calibration.toml [ground]).

Cost, measured on h200 (2026-10-15) over the seven continental extracts:
scripts/osm_roads.sh filters them in 573 s wall, in parallel, at 8.3 GB of
summed osmium RSS, to 424 MB; `ways` parses that in 117 s at 10.2 GB peak
RSS (3.39 M ways, cached); `motorway_mask` takes 36-48 s per rule over the
10 M-cell index (cached per index). The filter is an install step like the
rail one, and the build host's tools/bin has osmium.
"""

from __future__ import annotations

import hashlib
import pathlib
import re

import numpy as np
import polars as pl

from .. import config
from ._utils import _atomic_write, _params_hash

#: Bumped whenever `_ways` reads a different set of ways or tags.
PARSER_VERSION = 1
#: The ways sources/osm-style filtering keeps (scripts/osm_roads.sh).
HIGHWAYS = ("motorway", "trunk")
#: A trunk tagged as a grade-separated road in any of OSM's three spellings.
EXPRESSWAY_TAGS = ("motorway", "expressway", "motorroad")
#: Which ways make a cell a motorway cell. "motorway": highway=motorway only;
#: "expressway": also trunk tagged motorway=, expressway= or motorroad=yes;
#: "fast_trunk": also trunk signed FAST_TRUNK_KMH or more. "fast_trunk" was
#: chosen out of fold with the speeds (calibration.toml [ground] says by how
#: much); FAST_TRUNK_KMH is a round threshold, not fitted.
RULES = ("motorway", "expressway", "fast_trunk", "any")
RULE = "fast_trunk"
FAST_TRUNK_KMH = 100.0
#: Spacing of the points a way is sampled at before each is given its cell.
#: Under a third of a resolution-7 cell's edge (1.4 km), so a way cannot
#: cross a cell between two samples except at a corner.
DENSIFY_KM = 0.4

ROADS_GLOB = "*-roads.osm.pbf"
SCHEMA = {"way_id": pl.Int64, "highway": pl.Utf8, "expressway": pl.Boolean,
          "maxspeed_kmh": pl.Float64, "lat": pl.List(pl.Float64), "lon": pl.List(pl.Float64)}

_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph)?", re.IGNORECASE)


def parse_maxspeed(raw: str | None) -> float | None:
    """km/h from an OSM maxspeed value: "100", "70 mph", "100;80" (the first).
    None for "none", "signals", zone codes and anything else not a number."""
    if not raw:
        return None
    m = _NUMBER.match(raw.split(";")[0])
    if not m:
        return None
    v = float(m.group(1))
    return v * 1.609344 if m.group(2) else v


def _ways(path) -> list[dict]:
    """Every motorway and trunk way in one filtered extract, with its nodes'
    coordinates."""
    import osmium

    rows = []
    # Nodes must be read for the location cache; only ways are yielded.
    fp = (osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY).with_locations()
          .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY)))
    for w in fp:
        hw = w.tags.get("highway")
        if hw not in HIGHWAYS:
            continue
        lat, lon = [], []
        for n in w.nodes:
            if n.location.valid():
                lat.append(n.location.lat)
                lon.append(n.location.lon)
        if len(lat) < 2:
            continue
        rows.append({"way_id": w.id, "highway": hw,
                     "expressway": any(w.tags.get(k) == "yes" for k in EXPRESSWAY_TAGS),
                     "maxspeed_kmh": parse_maxspeed(w.tags.get("maxspeed")),
                     "lat": lat, "lon": lon})
    return rows


def _ways_cache_path(fingerprint) -> pathlib.Path:
    key = _params_hash(PARSER_VERSION, HIGHWAYS, EXPRESSWAY_TAGS, fingerprint)
    return config.CACHE / f"motorway_ways-{key}.parquet"


def _paths(extracts_dir) -> list[pathlib.Path]:
    paths = sorted(extracts_dir.glob(ROADS_GLOB))
    if not paths:
        raise FileNotFoundError(
            f"no {ROADS_GLOB} in {extracts_dir}; run scripts/osm_roads.sh first")
    return paths


def ways(*, extracts_dir=None) -> tuple[pl.DataFrame, str]:
    """(every motorway and trunk way, the key of the extracts it came from).
    A way mapped in two regional extracts is kept once."""
    from .osm import _fingerprint

    extracts_dir = extracts_dir or (config.CACHE / "osm")
    paths = _paths(extracts_dir)
    cached = _ways_cache_path(_fingerprint(extracts_dir, paths))
    if cached.exists():
        return pl.read_parquet(cached), cached.stem
    rows = []
    for p in paths:
        before = len(rows)
        rows.extend(_ways(p))
        print(f"  {p.name}: {len(rows) - before:,} motorway and trunk ways", flush=True)
    df = pl.DataFrame(rows, schema=SCHEMA).unique(subset=["way_id"], keep="first")
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df, cached.stem


def selected(df: pl.DataFrame, rule: str = RULE) -> pl.DataFrame:
    """The ways `rule` counts as motorway."""
    if rule not in RULES:
        raise ValueError(f"unknown motorway rule {rule!r}; one of {RULES}")
    if rule == "any":
        return df
    keep = pl.col("highway") == "motorway"
    if rule in ("expressway", "fast_trunk"):
        keep = keep | pl.col("expressway")
    if rule == "fast_trunk":
        keep = keep | (pl.col("maxspeed_kmh") >= FAST_TRUNK_KMH)
    return df.filter(keep)


def densify(lat: np.ndarray, lon: np.ndarray, starts: np.ndarray,
            step_km: float = DENSIFY_KM, with_way: bool = False):
    """Points every `step_km` or closer along polylines, their vertices
    included. `lat`/`lon` are all ways' nodes end to end and `starts` the
    index of each way's first node. A segment across the antimeridian is
    left out rather than drawn the long way round the globe."""
    ends = np.r_[starts[1:], len(lat)]
    seg = np.ones(len(lat), dtype=bool)
    seg[ends - 1] = False                          # no segment from a way's last node
    i = np.flatnonzero(seg[:-1] if len(seg) else seg)
    i = i[np.abs(lon[i + 1] - lon[i]) < 180.0]
    dy = (lat[i + 1] - lat[i]) * 111.0
    dx = (lon[i + 1] - lon[i]) * 111.0 * np.cos(np.radians(0.5 * (lat[i] + lat[i + 1])))
    n = np.maximum(1, np.ceil(np.hypot(dx, dy) / step_km).astype(np.int64))
    which = np.repeat(np.arange(len(i)), n)
    t = (np.arange(len(which)) - np.repeat(np.cumsum(n) - n, n)) / n[which]
    a = i[which]
    plat = lat[a] + t * (lat[a + 1] - lat[a])
    plon = lon[a] + t * (lon[a + 1] - lon[a])
    # The last node of each segment: t never reaches 1 above.
    if not with_way:
        return np.r_[plat, lat[i + 1]], np.r_[plon, lon[i + 1]]
    way_of_node = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(lat)]))
    return (np.r_[plat, lat[i + 1]], np.r_[plon, lon[i + 1]],
            np.r_[way_of_node[a], way_of_node[i + 1]])


def _mask_cache_path(cells: list[str], ways_key: str, rule: str = RULE) -> pathlib.Path:
    """Keyed on the rule and its constants, the sampling, the ways' own key
    (their extracts and parser) and every cell of the index."""
    key = _params_hash(rule, FAST_TRUNK_KMH, DENSIFY_KM,
                       ways_key, hashlib.sha256("".join(cells).encode()).hexdigest())
    return config.CACHE / f"motorway_mask-{key}.parquet"


def motorway_mask(idx, rule: str = RULE, *, extracts_dir=None) -> np.ndarray:
    """True for every cell of `idx` a motorway (under `rule`) crosses: the
    fine cell where the base cell was split, else the base cell."""
    import h3

    df, key = ways(extracts_dir=extracts_dir)
    cached = _mask_cache_path(list(idx.cells), key, rule)
    if cached.exists():
        return pl.read_parquet(cached)["motorway"].to_numpy()
    sel = selected(df, rule)
    lens = sel["lat"].list.len().to_numpy()
    starts = np.r_[0, np.cumsum(lens)[:-1]].astype(np.int64)
    lat = sel["lat"].explode(empty_as_null=True).to_numpy()   # every way has 2+ nodes
    lon = sel["lon"].explode(empty_as_null=True).to_numpy()
    plat, plon = densify(lat, lon, starts)
    # As NodeIndex.cell_at looks a point up: its base cell, and the fine cell
    # at the point where that base cell was split. Not the fine cell's
    # parent: H3 children do not nest inside their parent's outline, and a
    # point near a split cell's edge has a fine cell whose parent is the
    # neighbour.
    split = idx._split
    mask = np.zeros(idx.n_cells, dtype=bool)
    hit = set()
    for la, lo in zip(plat.tolist(), plon.tolist()):
        base = h3.latlng_to_cell(la, lo, config.SOLVE_RES)
        hit.add(h3.latlng_to_cell(la, lo, config.FINE_RES) if base in split else base)
    for c in hit:
        pos = idx.try_cell_index(c)
        if pos is not None:
            mask[pos] = True
    _atomic_write(cached, lambda tmp: pl.DataFrame({"motorway": mask}).write_parquet(tmp))
    print(f"  motorways ({rule}): {len(sel):,} ways, {len(plat):,} points, "
          f"{int(mask.sum()):,} cells", flush=True)
    return mask



#: Upper edges of the signed-limit bands of a motorway cell, km/h; band 0 is a
#: cell no crossing way carries a maxspeed for.
LIMIT_BANDS_KMH = (95.0, 115.0)


def limit_band_of(kmh: np.ndarray) -> np.ndarray:
    """0 for no signed limit (NaN), else 1 + the band of the limit."""
    kmh = np.asarray(kmh, dtype=float)
    out = 1 + np.searchsorted(np.asarray(LIMIT_BANDS_KMH), np.nan_to_num(kmh), side="right")
    return np.where(np.isfinite(kmh), out, 0).astype(np.int64)


def motorway_limit(idx, rule: str = RULE, *, extracts_dir=None) -> np.ndarray:
    """The highest signed limit (km/h) among the ways under `rule` crossing
    each cell of `idx`, NaN where none carries one -- the cell assignment
    `motorway_mask` makes."""
    import h3

    df, key = ways(extracts_dir=extracts_dir)
    cached = config.CACHE / (f"motorway_limit-"
                             f"{_mask_cache_path(list(idx.cells), key, rule).stem.split('-', 1)[1]}.parquet")
    if cached.exists():
        return pl.read_parquet(cached)["limit"].to_numpy()
    sel = selected(df, rule)
    lens = sel["lat"].list.len().to_numpy()
    starts = np.r_[0, np.cumsum(lens)[:-1]].astype(np.int64)
    lat = sel["lat"].explode(empty_as_null=True).to_numpy()
    lon = sel["lon"].explode(empty_as_null=True).to_numpy()
    plat, plon, way = densify(lat, lon, starts, with_way=True)
    limit = sel["maxspeed_kmh"].to_numpy().astype(float)
    have = np.isfinite(limit[way])
    split = idx._split
    best: dict[str, float] = {}
    for la, lo, v in zip(plat[have].tolist(), plon[have].tolist(), limit[way][have].tolist()):
        base = h3.latlng_to_cell(la, lo, config.SOLVE_RES)
        c = h3.latlng_to_cell(la, lo, config.FINE_RES) if base in split else base
        if v > best.get(c, -1.0):
            best[c] = v
    out = np.full(idx.n_cells, np.nan)
    for c, v in best.items():
        pos = idx.try_cell_index(c)
        if pos is not None:
            out[pos] = v
    _atomic_write(cached, lambda tmp: pl.DataFrame({"limit": out}).write_parquet(tmp))
    return out
