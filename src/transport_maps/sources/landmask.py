"""Natural Earth land polygons -> the H3 cell universe."""

import os
import pathlib
import tempfile
from collections.abc import Callable

import h3
import httpx
import polars as pl
import pyogrio
import shapely

from transport_maps import config

LAND_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"

# A part is Antarctic -- and dropped -- when its northernmost point (bounds[3],
# the max latitude) does NOT exceed this value, i.e. `max_lat <= -60.0` is
# dropped and `max_lat > -60.0` is kept (see the strict `>` filter below). H3
# cannot polyfill a shape that wraps a pole, and Antarctica has no scheduled
# service, so it is excluded.
ANTARCTICA_MAX_LAT = -60.0

_MULTIPOLYGON_TYPE_ID = 6


def _atomic_write(path: pathlib.Path, write_fn: Callable[[pathlib.Path], None]) -> None:
    """Write via a same-directory temp file, then atomically replace `path`.

    `write_fn` receives the temp file's path and must write the full content
    to it. Same-directory rename is atomic on POSIX, so a process killed
    mid-write can never leave a truncated file at `path` for the next run's
    `.exists()` check to mistake for a complete, valid cache entry.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp_path = pathlib.Path(tmp_name)
    try:
        write_fn(tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _download() -> pathlib.Path:
    config.ensure_dirs()
    cached = config.CACHE / "ne_10m_land.zip"
    if not cached.exists():
        r = httpx.get(LAND_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    return cached


def _land_parts() -> list[shapely.Geometry]:
    """Single polygons covering land, excluding Antarctica."""
    path = _download().resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    try:
        geom_column = next(c for c in table.schema.names if "geom" in c.lower())
    except StopIteration:
        raise RuntimeError(
            f"no geometry column found in Natural Earth archive; columns: {table.schema.names}"
        ) from None
    geoms = shapely.from_wkb(table.column(geom_column).to_pylist())

    parts: list[shapely.Geometry] = []
    for g in geoms:
        if shapely.get_type_id(g) == _MULTIPOLYGON_TYPE_ID:
            parts.extend(shapely.get_parts(g))
        else:
            parts.append(g)

    kept = [p for p in parts if p.bounds[3] > ANTARCTICA_MAX_LAT]
    if not kept:
        raise RuntimeError("no land parts parsed from Natural Earth archive")
    return kept


def land_cells(res: int) -> list[str]:
    """H3 cells at `res` overlapping land. Cached to parquet."""
    config.ensure_dirs()
    out = config.BUILD / f"land_cells_r{res}.parquet"
    if out.exists():
        return pl.read_parquet(out)["cell"].to_list()

    cells: set[str] = set()
    failures: list[tuple[tuple[float, ...], str, str]] = []
    for poly in _land_parts():
        try:
            shape = h3.geo_to_h3shape(poly)
            cells.update(h3.h3shape_to_cells_experimental(shape, res, contain="overlap"))
        except Exception as exc:  # noqa: BLE001 -- any polyfill failure must be surfaced, not just H3FailedError
            failures.append((poly.bounds, type(exc).__name__, str(exc)))

    if failures:
        raise RuntimeError(f"{len(failures)} land parts failed to cellify: {failures[:5]}")

    ordered = sorted(cells)
    _atomic_write(out, lambda tmp: pl.DataFrame({"cell": ordered}).write_parquet(tmp))
    return ordered
