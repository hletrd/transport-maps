"""GRIP4 road-density rasters -> per-location road class.

GRIP4 ships one density grid per road type at 5 arcmin. We reduce them to a single
"best grade present" grid: 1 = highway, 5 = local road, 0 = roadless.
"""

import zipfile
from pathlib import Path

import h3
import numpy as np
import rasterio

from transport_maps import config
from transport_maps.sources import _fetch
from transport_maps.sources._utils import _atomic_write, _params_hash

GRIP4_URL = "https://dataportaal.pbl.nl/downloads/GRIP4/GRIP4_density_tp{n}.zip"
GRID_ROWS, GRID_COLS = 2160, 4320  # 5 arcmin global; verified against the real rasters
N_TYPES = 5
# Density below this is noise rather than usable road. NoData (-9999) falls below
# it automatically, so no separate NoData mask is needed here.
DENSITY_THRESHOLD = 1.0

_grid_cache: np.ndarray | None = None


def _archive(road_type: int) -> _fetch.Fingerprint:
    """One GRIP4 density archive, checked against the upstream once per build.

    The archive itself is kept, not only the raster extracted from it: without
    it there is nothing to ask the upstream about (G2). Streamed to disk by
    `_fetch`; the old in-memory download held the whole zip as bytes.
    """
    url = GRIP4_URL.format(n=road_type)
    return _fetch.fetch(url, config.CACHE / "grip4" / url.rsplit("/", 1)[-1], timeout=300)


def _ensure_raster(road_type: int) -> Path:
    """One GRIP4 density raster, extracted from its archive into config.CACHE.

    Named by the archive's hash, so a new archive is a new raster rather than
    the old one found by name.
    """
    archive = _archive(road_type)
    target = (config.CACHE / "grip4"
              / f"grip4_tp{road_type}_dens_m_km2-{archive.sha256[:12]}.asc")
    if target.exists():
        return target

    with zipfile.ZipFile(archive.path) as z:
        member = next(
            (n for n in z.namelist() if n.lower().endswith(f"tp{road_type}_dens_m_km2.asc")),
            None,
        )
        if member is None:
            raise RuntimeError(f"{archive.url} has no tp{road_type} density raster: "
                               f"{z.namelist()}")

        def _extract(tmp: Path) -> None:
            with z.open(member) as src, tmp.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
        _atomic_write(target, _extract)

    return target


def _sources() -> list[str]:
    """The sha256 of every GRIP4 archive, best grade first, after checking each."""
    return [_archive(n).sha256 for n in range(1, N_TYPES + 1)]


def _grid_cache_path(sources: list[str]):
    """Cache path stamped with the constants that determine the grid's content,
    and with `sources`, the archives' hashes (`_sources()`).

    Without the stamp, lowering DENSITY_THRESHOLD and re-running `build-all`
    reads back the grid built under the old threshold, so the change silently
    no-ops and every test still passes against the stale file.
    """
    # GRIP4_URL too: a new host or dataset version must miss, not read back
    # the grid built from the old rasters. And the archives' content: a new
    # release under the same URL is a new grid (G2).
    stamp = _params_hash(GRIP4_URL, DENSITY_THRESHOLD, GRID_ROWS, GRID_COLS, N_TYPES, sources)
    return config.BUILD / f"road_class_grid_{stamp}.npy"


def road_class_grid() -> np.ndarray:
    """Best road grade per 5-arcmin cell. 0 = roadless, 1 = highway .. 5 = local."""
    global _grid_cache
    if _grid_cache is not None:
        return _grid_cache

    cached = _grid_cache_path(_sources())
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

    def _write(tmp: Path) -> None:
        # np.save(path, ...) on a bare path appends ".npy" if missing, which
        # would write past the atomic temp file instead of into it -- pass an
        # explicitly closed file object so the bytes land exactly at `tmp`
        # before the rename below runs.
        with tmp.open("wb") as f:
            np.save(f, best)

    config.ensure_dirs()
    _atomic_write(cached, _write)
    _grid_cache = best
    return best


def cell_class(cells: list[str]) -> np.ndarray:
    """Best road grade anywhere inside each H3 cell's footprint.

    An H3 res-6 cell is about 36 km2; a GRIP4 cell is about 86 km2 at the
    equator and 43 km2 at 60 degrees, so the footprint window spans 1-4 GRIP4
    cells (the 51.5 % -> 29.3 % roadless figures were measured at res 5, 2026-09).
    Sampling only the centroid therefore under-reports road access badly.
    Measured over 6,000 random land cells:

        roadless      centroid 51.5%  ->  footprint 29.3%
        mean speed    23.9 km/h       ->  36.8 km/h
        cells improved by footprint   ->  39.4%
        cells made worse              ->  0.00% (a superset cannot be worse)

    The spec says "the highest-grade road class present in it" -- present in the
    cell, not at its centre. Measured (not estimated) full pass over the
    res-5 grid's 548,557 cells: 4.77 seconds. cell_class runs over the base
    cells, of which the res-6 build has 4,091,715 -- about 7.5x, not the 25x
    an earlier note claimed (that figure counted the refined res-7 children,
    which this pass never sees). The point of the measurement is that the pass
    is linear and cheap, not the absolute figure.
    """
    grid = road_class_grid()
    n = len(cells)
    if n == 0:
        return np.zeros(0, dtype=np.uint8)
    # Every cell's footprint box at once; the per-cell loop that read each box
    # through scalar np.clip calls was ~150 s of the build's setup (py-spy,
    # 2026-10-07). Same boxes, same windows, same minimum.
    lat_min = np.empty(n)
    lat_max = np.empty(n)
    lon_min = np.empty(n)
    lon_max = np.empty(n)
    for i, cell in enumerate(cells):
        boundary = h3.cell_to_boundary(cell)
        lats = [p[0] for p in boundary]
        lons = [p[1] for p in boundary]
        lat_min[i], lat_max[i] = min(lats), max(lats)
        lon_min[i], lon_max[i] = min(lons), max(lons)
    wraps = lon_max - lon_min > 180.0
    r0 = _rows_of(lat_max)
    r1 = _rows_of(lat_min)
    c0 = _cols_of(lon_min)
    c1 = _cols_of(lon_max)
    # Lower class number = better grade; 0 means no road of any type, so it
    # stands in as the worst value while taking the minimum over the window.
    none = np.iinfo(np.uint8).max
    best = np.full(n, none, dtype=np.uint8)
    # Most windows are 1-4 grid cells a side and go through whole-array
    # passes, one per (row, column) offset. A few are far wider -- a cell near
    # a pole spans many columns -- and one of those would make every pass run
    # thousands of times over all 4 M cells (it did: 1,390 s on h200), so they
    # are read one by one, as before.
    small = ~wraps & (r1 - r0 < WINDOW_MAX) & (c1 - c0 < WINDOW_MAX)
    sr0, sr1, sc0, sc1 = r0[small], r1[small], c0[small], c1[small]
    sbest = np.full(len(sr0), none, dtype=np.uint8)
    for dr in range(WINDOW_MAX):
        for dc in range(WINDOW_MAX):
            inside = (sr0 + dr <= sr1) & (sc0 + dc <= sc1)
            if not inside.any():
                continue
            v = grid[np.minimum(sr0 + dr, sr1), np.minimum(sc0 + dc, sc1)]
            v = np.where(inside & (v > 0), v, none).astype(np.uint8)
            np.minimum(sbest, v, out=sbest)
    best[small] = sbest
    for i in np.flatnonzero(~small & ~wraps):
        window = grid[r0[i]:r1[i] + 1, c0[i]:c1[i] + 1]
        present = window[window > 0]
        if present.size:
            best[i] = present.min()
    out = np.where(best == none, 0, best).astype(np.uint8)
    if wraps.any():
        # Antimeridian wrap makes the bounding box meaningless; use the centroid.
        centres = np.array([h3.cell_to_latlng(cells[i]) for i in np.flatnonzero(wraps)])
        out[wraps] = sample_class(centres[:, 0], centres[:, 1])
    return out


# Widest window, in grid cells a side, read by the whole-array passes.
WINDOW_MAX = 6


def _rows_of(lat: np.ndarray) -> np.ndarray:
    return np.clip((90.0 - lat) * GRID_ROWS / 180.0, 0, GRID_ROWS - 1).astype(np.int64)


def _cols_of(lon: np.ndarray) -> np.ndarray:
    return np.clip((lon + 180.0) * GRID_COLS / 360.0, 0, GRID_COLS - 1).astype(np.int64)


def _row_of(lat: float) -> int:
    return int(np.clip((90.0 - lat) * GRID_ROWS / 180.0, 0, GRID_ROWS - 1))


def _col_of(lon: float) -> int:
    return int(np.clip((lon + 180.0) * GRID_COLS / 360.0, 0, GRID_COLS - 1))


def sample_class(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Road class at each coordinate. Vectorised nearest-cell lookup."""
    grid = road_class_grid()
    rows = np.clip(((90.0 - lats) * GRID_ROWS / 180.0).astype(np.int64), 0, GRID_ROWS - 1)
    cols = np.clip(((lons + 180.0) * GRID_COLS / 360.0).astype(np.int64), 0, GRID_COLS - 1)
    return grid[rows, cols]
