"""Which land cells are built up, and by how much traffic slows them.

GRIP4 gives a cell the grade of the best road inside it, so a dense city cell
containing a motorway is charged at motorway speed. Measured against 112 real
city-to-airport journeys, that made urban access 2.03x too fast, while
inter-town driving over 1,383 journeys was only 1.12x out -- the error is
almost entirely in built-up areas, not on the open road.

City POPULATION barely predicts it (correlation +0.15 with log10 population;
the median ratio is 1.9 at under a million and 2.1 above five million), so this
is a flat factor over a radius rather than anything scaled by size.
"""

from __future__ import annotations

import hashlib
import pathlib

import h3
import numpy as np
import polars as pl
import pyogrio

from .. import config
from . import _fetch
from ._utils import _atomic_write, _params_hash


def load_urban_calibration(path=None) -> tuple[float, float, float]:
    """calibration.toml [urban]: (pop_min, radius_km, congestion_factor).

    All three FITTED jointly against both journey sets: this setting brings
    urban access from 2.03x to 1.02x and inter-town from 1.12x to 1.06x, and
    marks 5.7% of land as built up. calibration.toml carries the provenance.
    They lived here as literals until task B2 (2026-10-02), with the same
    values; tests/test_calibration_moved.py pins them, and the urban-mask
    cache key with them.
    """
    import tomllib

    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)["urban"]
    # float(): the cache key below digests these through json, which writes
    # 200000 and 200000.0 differently. A TOML integer must not move the key.
    pop_min, radius_km, factor = (float(raw["pop_min"]), float(raw["radius_km"]),
                                  float(raw["congestion_factor"]))
    if not (pop_min > 0 and radius_km > 0 and factor >= 1.0):
        raise ValueError(f"{path} [urban] needs pop_min > 0, radius_km > 0 and "
                         f"congestion_factor >= 1; got {pop_min}, {radius_km}, {factor}")
    return pop_min, radius_km, factor


# Read once, at import. The mask cache keys on the first two; the third only
# divides speeds (graph/ground.cell_speed_kmh) and is in no cache.
URBAN_POP_MIN, URBAN_RADIUS_KM, URBAN_CONGESTION_FACTOR = load_urban_calibration()

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


def _places() -> tuple[np.ndarray, np.ndarray]:
    """Coordinates of places above the population threshold."""
    path = _download().resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    lat = np.array(table.column("latitude").to_pylist(), dtype=float)
    lon = np.array(table.column("longitude").to_pylist(), dtype=float)
    pop = np.array(table.column("pop_max").to_pylist(), dtype=float)
    keep = pop >= URBAN_POP_MIN
    return lat[keep], lon[keep]


def _mask_cache_path(cells: list[str], source: str) -> pathlib.Path:
    """Keyed on the constants, the source archive AND every cell: two universes
    of the same length and ends (a re-refined grid) must not share an entry.
    The archive by URL and by `source`, its sha256: a new release of the
    places under the same URL moves the cities the mask is drawn around (G2)."""
    key = _params_hash(URBAN_POP_MIN, URBAN_RADIUS_KM, PLACES_URL,
                       hashlib.sha256("".join(cells).encode()).hexdigest(), source)
    return config.CACHE / f"urban_mask-{key}.parquet"


def urban_mask(cells: list[str]) -> np.ndarray:
    """True where a cell lies within `URBAN_RADIUS_KM` of a sizeable city."""
    cached = _mask_cache_path(cells, _source().sha256)
    if cached.exists():
        return pl.read_parquet(cached)["urban"].to_numpy()

    centres = np.array([h3.cell_to_latlng(c) for c in cells])
    lat, lon = _places()
    mask = np.zeros(len(cells), dtype=bool)
    coslat = np.cos(np.radians(centres[:, 0]))
    for la, lo in zip(lat, lon):
        d = np.hypot((centres[:, 0] - la) * 111.0,
                     (centres[:, 1] - lo) * 111.0 * coslat)
        mask |= d <= URBAN_RADIUS_KM

    _atomic_write(cached, lambda tmp: pl.DataFrame({"urban": mask}).write_parquet(tmp))
    return mask
