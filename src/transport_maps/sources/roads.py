"""GRIP4 road-density rasters -> per-location road class.

GRIP4 ships one density grid per road type at 5 arcmin. We reduce them to a single
"best grade present" grid: 1 = highway, 5 = local road, 0 = roadless, and
NO_DATA where GRIP4 has no data at all (its own coastline is coarser than ours).
`cell_class` then fills the cells GRIP4 cannot speak for -- see its docstring.
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
# Density below this is noise rather than usable road.
DENSITY_THRESHOLD = 1.0
# GRIP4's NoData. It is not "no roads": it is GRIP4's sea, NoData in all five
# rasters at once (7,065,184 of 9,331,200 grid cells; never in some and not
# others), and its coastline is coarse enough to drown real cities. Sochi's
# whole 3x3 window, Male, and half of Zanzibar's and Beira's are NoData, and
# reading them as roadless put those city cores at walking pace (audit of
# 2026-10-14: own-cell times of 28-63 min).
GRIP4_NODATA = -9999.0
# Grid value for a cell that is NoData in every raster. Distinct from 0, which
# is a valid cell with no road above DENSITY_THRESHOLD.
NO_DATA = 9
# The class a cell is given where it plainly has streets but GRIP4 does not
# say so: local road (calibration.toml [ground] local_kmh).
LOCAL_CLASS = 5
# GeoNames cities15000, the gazetteer's own input (emit/places.py CITIES_URL).
CITIES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
# Built-up density that turns a place's population into the radius it covers:
# r = sqrt(pop / (pi * density)). PUBLISHED-FIGURE DEFAULT: Demographia World
# Urban Areas (2023), 4,200 people per km2 averaged over the ~1,000 urban
# areas above 500,000. A town of 15,000 covers 1.1 km, a city of 1 M 8.7 km.
SETTLED_DENSITY_PER_KM2 = 4200.0

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
    stamp = _params_hash(GRIP4_URL, DENSITY_THRESHOLD, GRID_ROWS, GRID_COLS, N_TYPES,
                         NO_DATA, sources)
    return config.BUILD / f"road_class_grid_{stamp}.npy"


def road_class_grid() -> np.ndarray:
    """Best road grade per 5-arcmin cell. 0 = roadless, 1 = highway .. 5 = local,
    NO_DATA = GRIP4 has no data there in any raster."""
    global _grid_cache
    if _grid_cache is not None:
        return _grid_cache

    cached = _grid_cache_path(_sources())
    if cached.exists():
        _grid_cache = np.load(cached)
        return _grid_cache

    best = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.uint8)
    no_data = np.ones((GRID_ROWS, GRID_COLS), dtype=bool)
    for road_type in range(N_TYPES, 0, -1):  # worst grade first, best overwrites
        path = _ensure_raster(road_type)
        with rasterio.open(path) as src:
            band = src.read(1)
        if band.shape != (GRID_ROWS, GRID_COLS):
            raise RuntimeError(f"{path} has shape {band.shape}, expected {(GRID_ROWS, GRID_COLS)}")
        best[band >= DENSITY_THRESHOLD] = road_type
        no_data &= band <= GRIP4_NODATA
    best[no_data] = NO_DATA

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


_density_cache: np.ndarray | None = None


def road_density_grid() -> np.ndarray:
    """Total road density per 5-arcmin cell, metres per km2: GRIP4's five
    density rasters summed, NoData read as 0.

    The class grid keeps only the best grade present, which a city core with
    a motorway through it shares with the motorway's rural stretch; the total
    density is what tells them apart (a dense street grid is thousands of
    metres per km2, a lone highway a few hundred)."""
    global _density_cache
    if _density_cache is not None:
        return _density_cache
    cached = config.BUILD / (f"road_density_grid_"
                             f"{_params_hash(GRIP4_URL, GRID_ROWS, GRID_COLS, N_TYPES, _sources())}.npy")
    if cached.exists():
        _density_cache = np.load(cached)
        return _density_cache
    total = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.float32)
    for road_type in range(1, N_TYPES + 1):
        with rasterio.open(_ensure_raster(road_type)) as src:
            band = src.read(1)
        if band.shape != (GRID_ROWS, GRID_COLS):
            raise RuntimeError(f"tp{road_type} has shape {band.shape}, expected {(GRID_ROWS, GRID_COLS)}")
        total += np.where(band > GRIP4_NODATA, np.maximum(band, 0), 0).astype(np.float32)

    def _write(tmp: Path) -> None:
        with tmp.open("wb") as f:
            np.save(f, total)

    config.ensure_dirs()
    _atomic_write(cached, _write)
    _density_cache = total
    return total


def cell_road_density(cells: list[str]) -> np.ndarray:
    """Total road density (m/km2) at each H3 cell's centroid, from
    `road_density_grid`."""
    if not len(cells):
        return np.zeros(0, dtype=np.float32)
    centres = np.array([h3.cell_to_latlng(c) for c in cells], dtype=float)
    return road_density_grid()[_rows_of(centres[:, 0]), _cols_of(centres[:, 1])]


def footprint_class(cells: list[str], pad: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """(best road grade anywhere inside each H3 cell's footprint, whether
    GRIP4 has data anywhere in it), the window widened by `pad` grid cells
    a side.

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

    The grade is 0 where no road is present; `known` is False where every
    grid cell in the window is NO_DATA, so that there 0 means "GRIP4 cannot
    say", not "no road".
    """
    grid = road_class_grid()
    n = len(cells)
    if n == 0:
        return np.zeros(0, dtype=np.uint8), np.zeros(0, dtype=bool)
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
    r0 = np.maximum(_rows_of(lat_max) - pad, 0)
    r1 = np.minimum(_rows_of(lat_min) + pad, GRID_ROWS - 1)
    c0 = np.maximum(_cols_of(lon_min) - pad, 0)
    c1 = np.minimum(_cols_of(lon_max) + pad, GRID_COLS - 1)
    # Lower class number = better grade; 0 means no road of any type, so it
    # stands in as the worst value while taking the minimum over the window.
    none = np.iinfo(np.uint8).max
    best = np.full(n, none, dtype=np.uint8)
    known = np.zeros(n, dtype=bool)
    # Most windows are 1-4 grid cells a side and go through whole-array
    # passes, one per (row, column) offset. A few are far wider -- a cell near
    # a pole spans many columns -- and one of those would make every pass run
    # thousands of times over all 4 M cells (it did: 1,390 s on h200), so they
    # are read one by one, as before.
    width = WINDOW_MAX + 2 * pad
    small = ~wraps & (r1 - r0 < width) & (c1 - c0 < width)
    sr0, sr1, sc0, sc1 = r0[small], r1[small], c0[small], c1[small]
    sbest = np.full(len(sr0), none, dtype=np.uint8)
    sknown = np.zeros(len(sr0), dtype=bool)
    for dr in range(width):
        for dc in range(width):
            inside = (sr0 + dr <= sr1) & (sc0 + dc <= sc1)
            if not inside.any():
                continue
            v = grid[np.minimum(sr0 + dr, sr1), np.minimum(sc0 + dc, sc1)]
            sknown |= inside & (v != NO_DATA)
            v = np.where(inside & (v > 0) & (v <= N_TYPES), v, none).astype(np.uint8)
            np.minimum(sbest, v, out=sbest)
    best[small] = sbest
    known[small] = sknown
    for i in np.flatnonzero(~small & ~wraps):
        window = grid[r0[i]:r1[i] + 1, c0[i]:c1[i] + 1]
        known[i] = bool((window != NO_DATA).any())
        present = window[(window > 0) & (window <= N_TYPES)]
        if present.size:
            best[i] = present.min()
    out = np.where(best == none, 0, best).astype(np.uint8)
    if wraps.any():
        # Antimeridian wrap makes the bounding box meaningless; use the centroid.
        centres = np.array([h3.cell_to_latlng(cells[i]) for i in np.flatnonzero(wraps)])
        raw = _sample_raw(centres[:, 0], centres[:, 1])
        out[wraps] = np.where(raw == NO_DATA, 0, raw)
        known[wraps] = raw != NO_DATA
    return out, known


def cell_class(cells: list[str]) -> np.ndarray:
    """Road grade per H3 cell: GRIP4's footprint grade, with the cells GRIP4
    cannot speak for filled in.

    GRIP4 has two kinds of 0, and neither is evidence of roadless land where
    people live (audit of 2026-10-14: the cores of Sochi, Beira, Zanzibar,
    Chita, Calumbo and Male at 5 km/h, 16 places of 100,000 or more):

    1. NO_DATA -- GRIP4's sea. A cell whose whole footprint is NoData takes
       the best grade one grid cell further out (~9 km), where GRIP4's coarse
       coastline cut it off from the land beside it; failing that, a cell in
       the urban mask (sources/urban.py) is given local roads; failing that it
       stays roadless, as an uninhabited coast or islet should.
    2. Zero density where a town stands: GRIP4 has holes in city cores
       (Chita's centre cell is 0 in all five rasters, with roads one cell
       over). A cell within a populated place's built-up radius -- GeoNames
       cities15000, r = sqrt(pop / (pi * SETTLED_DENSITY_PER_KM2)) -- has at
       least local roads.

    Both only raise a 0: to LOCAL_CLASS, or for rule 1 to the grade GRIP4
    reports beside the cell. A cell GRIP4 gives any road keeps it.
    """
    out, known = footprint_class(cells)
    gap = (out == 0) & ~known
    if gap.any():
        gi = np.flatnonzero(gap)
        wider, _ = footprint_class([cells[i] for i in gi], pad=1)
        out[gi] = wider
        still = gi[wider == 0]
        if len(still):
            from transport_maps.sources import urban

            in_city = urban.urban_mask([cells[i] for i in still])
            out[still[in_city]] = LOCAL_CLASS
    out[(out == 0) & settled_mask(cells)] = LOCAL_CLASS
    return out


def _settlements_source() -> _fetch.Fingerprint:
    """GeoNames cities15000, checked against the upstream once per build (G2):
    the same archive, at the same cache path, as the page's gazetteer."""
    return _fetch.fetch(CITIES_URL, config.CACHE / "cities15000.zip")


def _settlements() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(lat, lon, population) of GeoNames cities15000, with the gazetteer's
    own corrections (emit/places.py): a row it drops is not a town, and a
    quarter carrying its city's population counts as a town of its own."""
    import csv
    import io
    import zipfile

    from transport_maps.emit import places

    path = _settlements_source().path
    with zipfile.ZipFile(path) as z:
        text = z.read("cities15000.txt").decode("utf-8")
    lat, lon, pop = [], [], []
    for row in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            la, lo, p = float(row[4]), float(row[5]), int(row[14] or 0)
        except (IndexError, ValueError):
            continue
        gid = int(row[0]) if row[0].isdigit() else None
        if places.misplaced(gid, la, lo):
            continue
        lat.append(la)
        lon.append(lo)
        pop.append(max(places.ranked_population(gid, p), 15_000))
    return np.array(lat), np.array(lon), np.array(pop, dtype=float)


def settled_mask(cells: list[str]) -> np.ndarray:
    """True for each cell any part of which lies in a populated place's
    built-up disc: its centre within the radius plus one cell edge (a
    hexagon's circumradius). Measured on Beira, Zanzibar and Male, the centre
    alone left the airport islands and half the waterfront roadless: res-6
    centres are 6.4 km apart, wider than the radius of a town of 100,000."""
    out = np.zeros(len(cells), dtype=bool)
    if not cells:
        return out
    res = h3.get_resolution(cells[0])
    where = {c: i for i, c in enumerate(cells)}
    edge_km = h3.average_hexagon_edge_length(res, unit="km")
    step_km = np.sqrt(3.0) * edge_km               # centre-to-centre spacing
    lat, lon, pop = _settlements()
    reach = np.sqrt(pop / (np.pi * SETTLED_DENSITY_PER_KM2)) + edge_km
    for la, lo, r in zip(lat, lon, reach):
        home = h3.latlng_to_cell(la, lo, res)
        for c in h3.grid_disk(home, int(np.ceil(r / step_km))):
            i = where.get(c)
            if i is None or out[i]:
                continue
            if c == home or h3.great_circle_distance(
                    (la, lo), h3.cell_to_latlng(c), unit="km") <= r:
                out[i] = True
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


def _sample_raw(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    grid = road_class_grid()
    rows = np.clip(((90.0 - lats) * GRID_ROWS / 180.0).astype(np.int64), 0, GRID_ROWS - 1)
    cols = np.clip(((lons + 180.0) * GRID_COLS / 360.0).astype(np.int64), 0, GRID_COLS - 1)
    return grid[rows, cols]


def sample_class(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Road class at each coordinate, NO_DATA read as 0. Vectorised
    nearest-cell lookup."""
    raw = _sample_raw(lats, lons)
    return np.where(raw == NO_DATA, 0, raw).astype(np.uint8)
