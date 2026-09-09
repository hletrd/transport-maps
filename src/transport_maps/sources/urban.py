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

import pathlib

import h3
import httpx
import numpy as np
import polars as pl
import pyogrio

from .. import config
from ._utils import _atomic_write, _params_hash

# Fitted jointly against both journey sets: this setting brings urban access
# from 2.03x to 1.02x and inter-town from 1.12x to 1.06x, and marks 5.7% of
# land as built up.
URBAN_POP_MIN = 200_000.0
URBAN_RADIUS_KM = 40.0
URBAN_CONGESTION_FACTOR = 2.0

# Natural Earth populated places, for the urban mask only. The page's
# gazetteer (emit/places.py) moved to GeoNames; this stays on Natural Earth
# because the fitted radius and threshold above were measured against its
# pop_max column.
PLACES_URL = ("https://naturalearth.s3.amazonaws.com/10m_cultural/"
              "ne_10m_populated_places_simple.zip")
PLACES_ZIP = PLACES_URL.rsplit("/", 1)[-1]


def _download() -> pathlib.Path:
    """The populated-places archive, fetched once into the cache.

    Its own download, in this layer. This used to call emit.places._download,
    which had since grown a required `url` argument and fetches GeoNames, so
    a fresh cache raised TypeError in the index preamble -- and passing a URL
    would still have fetched the wrong dataset. The only reason a build ever
    got past here was an archive already sitting in data/cache.
    """
    config.ensure_dirs()
    cached = config.CACHE / PLACES_ZIP
    if not cached.exists():
        r = httpx.get(PLACES_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    return cached


def _places() -> tuple[np.ndarray, np.ndarray]:
    """Coordinates of places above the population threshold."""
    path = _download().resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    lat = np.array(table.column("latitude").to_pylist(), dtype=float)
    lon = np.array(table.column("longitude").to_pylist(), dtype=float)
    pop = np.array(table.column("pop_max").to_pylist(), dtype=float)
    keep = pop >= URBAN_POP_MIN
    return lat[keep], lon[keep]


def urban_mask(cells: list[str]) -> np.ndarray:
    """True where a cell lies within `URBAN_RADIUS_KM` of a sizeable city."""
    # The source archive is part of what the mask is derived from: a different
    # gazetteer must miss the cache, not be read back through it.
    key = _params_hash(URBAN_POP_MIN, URBAN_RADIUS_KM, PLACES_URL, len(cells),
                       cells[0] if cells else "", cells[-1] if cells else "")
    cached = config.CACHE / f"urban_mask-{key}.parquet"
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
