"""GRIP4 road-density rasters -> per-location road class.

GRIP4 ships one density grid per road type at 5 arcmin. We reduce them to a single
"best grade present" grid: 1 = highway, 5 = local road, 0 = roadless.
"""

import io
import zipfile
from pathlib import Path

import httpx
import numpy as np
import rasterio

from transport_maps import config
from transport_maps.sources._utils import _atomic_write

GRIP4_URL = "https://dataportaal.pbl.nl/downloads/GRIP4/GRIP4_density_tp{n}.zip"
GRID_ROWS, GRID_COLS = 2160, 4320  # 5 arcmin global; verified against the real rasters
N_TYPES = 5
# Density below this is noise rather than usable road. NoData (-9999) falls below
# it automatically, so no separate NoData mask is needed here.
DENSITY_THRESHOLD = 1.0

_grid_cache: np.ndarray | None = None


def _ensure_raster(road_type: int) -> Path:
    """Download and extract one GRIP4 density raster, cached under config.CACHE."""
    target = config.CACHE / "grip4" / f"grip4_tp{road_type}_dens_m_km2.asc"
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    url = GRIP4_URL.format(n=road_type)
    r = httpx.get(url, follow_redirects=True, timeout=300)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        member = next(
            (n for n in z.namelist() if n.lower().endswith(f"tp{road_type}_dens_m_km2.asc")),
            None,
        )
        if member is None:
            raise RuntimeError(f"{url} has no tp{road_type} density raster: {z.namelist()}")
        _atomic_write(target, lambda tmp: tmp.write_bytes(z.read(member)))

    return target


def road_class_grid() -> np.ndarray:
    """Best road grade per 5-arcmin cell. 0 = roadless, 1 = highway .. 5 = local."""
    global _grid_cache
    if _grid_cache is not None:
        return _grid_cache

    cached = config.BUILD / "road_class_grid.npy"
    if cached.exists():
        _grid_cache = np.load(cached)
        return _grid_cache

    best = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.uint8)
    for road_type in range(N_TYPES, 0, -1):  # worst grade first, best overwrites
        path = _ensure_raster(road_type)
        with rasterio.open(path) as src:
            band = src.read(1)
        if band.shape != (GRID_ROWS, GRID_COLS):
            raise RuntimeError(f"{path} has shape {band.shape}, expected {(GRID_ROWS, GRID_COLS)}")
        best[band >= DENSITY_THRESHOLD] = road_type

    config.ensure_dirs()
    np.save(cached, best)
    _grid_cache = best
    return best


def sample_class(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Road class at each coordinate. Vectorised nearest-cell lookup."""
    grid = road_class_grid()
    rows = np.clip(((90.0 - lats) * GRID_ROWS / 180.0).astype(np.int64), 0, GRID_ROWS - 1)
    cols = np.clip(((lons + 180.0) * GRID_COLS / 360.0).astype(np.int64), 0, GRID_COLS - 1)
    return grid[rows, cols]
