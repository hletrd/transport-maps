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

import h3
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

PLACES_ZIP = "ne_10m_populated_places_simple.zip"


def _places() -> tuple[np.ndarray, np.ndarray]:
    """Coordinates of places above the population threshold."""
    path = (config.CACHE / PLACES_ZIP).resolve()
    if not path.exists():
        from ..emit import places as places_mod

        places_mod._download()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    lat = np.array(table.column("latitude").to_pylist(), dtype=float)
    lon = np.array(table.column("longitude").to_pylist(), dtype=float)
    pop = np.array(table.column("pop_max").to_pylist(), dtype=float)
    keep = pop >= URBAN_POP_MIN
    return lat[keep], lon[keep]


def urban_mask(cells: list[str]) -> np.ndarray:
    """True where a cell lies within `URBAN_RADIUS_KM` of a sizeable city."""
    key = _params_hash(URBAN_POP_MIN, URBAN_RADIUS_KM, len(cells),
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
