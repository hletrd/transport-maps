"""Which land cells are built up, and by how much traffic slows them.

GRIP4 gives a cell the grade of the best road inside it, so a dense city cell
containing a motorway is charged at motorway speed. Measured against 112 real
city-to-airport journeys, that made urban access 2.03x too fast, while
inter-town driving over 1,383 journeys was only 1.12x out -- the error is
almost entirely in built-up areas, not on the open road.

How MUCH a city slows traffic barely depends on its size (correlation +0.15
with log10 population, 2026-09), so the factor is one number. How FAR the slow
streets reach does: a flat 20 km from every city of 200,000 covered a town
whole and left the outer half of London at highway speed. Since rebuild 31
the factor applies inside each city's own built-up radius
(`scaled_city_distance`), chosen out of fold over flat and scaled radii
(scripts/calibrate_ground.py).
"""

from __future__ import annotations

import hashlib
import pathlib

import h3
import numpy as np
import polars as pl
import pyogrio

from .. import config
from . import _fetch, roads
from ._utils import _atomic_write, _params_hash


def load_urban_calibration(path=None) -> tuple[float, float, float, float]:
    """calibration.toml [urban]: (pop_min, radius_km, built_up_factor,
    built_up_extent).

    `radius_km` draws the mask that decides which base cells are split to the
    finer grid (graph/refine.dense_mask). `built_up_factor` slows the roads of
    a cell less than `built_up_extent` built-up radii from a city
    (`scaled_city_distance`). calibration.toml carries the provenance of each.
    """
    import tomllib

    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)["urban"]
    # float(): the cache key below digests these through json, which writes
    # 200000 and 200000.0 differently. A TOML integer must not move the key.
    pop_min, radius_km, factor, extent = (
        float(raw["pop_min"]), float(raw["radius_km"]), float(raw["built_up_factor"]),
        float(raw["built_up_extent"]))
    if not (pop_min > 0 and radius_km > 0 and extent > 0 and factor >= 1.0):
        raise ValueError(f"{path} [urban] needs pop_min > 0, radius_km > 0, "
                         f"built_up_extent > 0 and built_up_factor >= 1; got {pop_min}, "
                         f"{radius_km}, {extent}, {factor}")
    return pop_min, radius_km, factor, extent


def load_urban_core(path=None) -> tuple[float, float]:
    """calibration.toml [urban]: (core_factor, core_extent) -- the second
    slowdown a city's core pays, inside `core_extent` built-up radii, on top
    of built_up_factor (rebuild 34)."""
    import tomllib

    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)["urban"]
    factor, extent = float(raw["core_factor"]), float(raw["core_extent"])
    if not (factor >= 1.0 and extent > 0):
        raise ValueError(f"{path} [urban] needs core_factor >= 1 and core_extent > 0; "
                         f"got {factor}, {extent}")
    return factor, extent


# Read once, at import. The masks' caches key on pop_min and their geometry;
# the factors and extents only decide speeds (graph/ground.cell_speed_kmh) and
# are in no cache.
(URBAN_POP_MIN, URBAN_RADIUS_KM, URBAN_BUILT_UP_FACTOR,
 URBAN_BUILT_UP_EXTENT) = load_urban_calibration()
URBAN_CORE_FACTOR, URBAN_CORE_EXTENT = load_urban_core()

# Natural Earth populated places, for the urban mask only. The page's
# gazetteer (emit/places.py) moved to GeoNames; this stays on Natural Earth
# because the fitted radius and threshold above were measured against its
# pop_max column.
PLACES_URL = ("https://naturalearth.s3.amazonaws.com/10m_cultural/"
              "ne_10m_populated_places_simple.zip")
PLACES_ZIP = PLACES_URL.rsplit("/", 1)[-1]


def _source() -> _fetch.Fingerprint:
    """The populated-places archive, checked against the upstream once per
    build (G2)."""
    config.ensure_dirs()
    return _fetch.fetch(PLACES_URL, config.CACHE / PLACES_ZIP)


def _download() -> pathlib.Path:
    """The populated-places archive, in the cache.

    Its own download, in this layer. This used to call emit.places._download,
    which had since grown a required `url` argument and fetches GeoNames, so
    a fresh cache raised TypeError in the index preamble -- and passing a URL
    would still have fetched the wrong dataset. The only reason a build ever
    got past here was an archive already sitting in data/cache.
    """
    return _source().path


def _places_with_pop() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Coordinates and pop_max of places above the population threshold."""
    path = _download().resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    lat = np.array(table.column("latitude").to_pylist(), dtype=float)
    lon = np.array(table.column("longitude").to_pylist(), dtype=float)
    pop = np.array(table.column("pop_max").to_pylist(), dtype=float)
    keep = pop >= URBAN_POP_MIN
    return lat[keep], lon[keep], pop[keep]


def _places() -> tuple[np.ndarray, np.ndarray]:
    """Coordinates of places above the population threshold."""
    lat, lon, _pop = _places_with_pop()
    return lat, lon


def city_radius_km(pop: np.ndarray) -> np.ndarray:
    """The built-up radius a city of `pop` covers at the published density
    sources/roads.py uses for towns, r = sqrt(pop / (pi * density)): 3.9 km
    at 200,000, 8.7 km at 1 M, 27 km at 10 M."""
    return np.sqrt(np.asarray(pop, dtype=float) / (np.pi * roads.SETTLED_DENSITY_PER_KM2))


def _scaled_cache_path(cells: list[str], source: str) -> pathlib.Path:
    """Keyed like the mask's, plus the density that turns a population into
    a radius."""
    key = _params_hash("scaled-city-distance", URBAN_POP_MIN, roads.SETTLED_DENSITY_PER_KM2,
                       PLACES_URL, hashlib.sha256("".join(cells).encode()).hexdigest(), source)
    return config.CACHE / f"city_scaled_distance-{key}.parquet"


def scaled_city_distance(cells: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Per cell, the smallest distance to a city of URBAN_POP_MIN or more
    measured in that city's built-up radius (`city_radius_km`) -- below 1 the
    cell is inside a built-up disc, 2 is one more radius out -- and that
    city's pop_max. A megacity's disc reaches 25-50 km and a 200,000-town's
    4 km, which one radius from every city cannot say."""
    cached = _scaled_cache_path(cells, _source().sha256)
    if cached.exists():
        df = pl.read_parquet(cached)
        return df["s"].to_numpy(), df["pop"].to_numpy()
    centres = np.array([h3.cell_to_latlng(c) for c in cells])
    lat, lon, pop = _places_with_pop()
    radius = city_radius_km(pop)
    out = np.full(len(cells), np.inf)
    which = np.zeros(len(cells))
    coslat = np.cos(np.radians(centres[:, 0]))
    for la, lo, r, p in zip(lat, lon, radius, pop):
        s = np.hypot((centres[:, 0] - la) * 111.0, (centres[:, 1] - lo) * 111.0 * coslat) / r
        closer = s < out
        out[closer], which[closer] = s[closer], p
    _atomic_write(cached, lambda tmp: pl.DataFrame({"s": out, "pop": which}).write_parquet(tmp))
    return out, which


def _mask_cache_path(cells: list[str], source: str,
                     radius_km: float = URBAN_RADIUS_KM) -> pathlib.Path:
    """Keyed on the constants, the source archive AND every cell: two universes
    of the same length and ends (a re-refined grid) must not share an entry.
    The archive by URL and by `source`, its sha256: a new release of the
    places under the same URL moves the cities the mask is drawn around (G2)."""
    key = _params_hash(URBAN_POP_MIN, radius_km, PLACES_URL,
                       hashlib.sha256("".join(cells).encode()).hexdigest(), source)
    return config.CACHE / f"urban_mask-{key}.parquet"


def urban_mask(cells: list[str], radius_km: float = URBAN_RADIUS_KM) -> np.ndarray:
    """True where a cell lies within `radius_km` of a sizeable city: the
    refinement mask (graph/refine.dense_mask)."""
    cached = _mask_cache_path(cells, _source().sha256, radius_km)
    if cached.exists():
        return pl.read_parquet(cached)["urban"].to_numpy()

    centres = np.array([h3.cell_to_latlng(c) for c in cells])
    lat, lon = _places()
    mask = np.zeros(len(cells), dtype=bool)
    coslat = np.cos(np.radians(centres[:, 0]))
    for la, lo in zip(lat, lon):
        d = np.hypot((centres[:, 0] - la) * 111.0,
                     (centres[:, 1] - lo) * 111.0 * coslat)
        mask |= d <= radius_km

    _atomic_write(cached, lambda tmp: pl.DataFrame({"urban": mask}).write_parquet(tmp))
    return mask
