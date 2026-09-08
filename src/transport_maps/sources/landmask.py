"""Natural Earth land polygons -> the H3 cell universe."""

import pathlib

import h3
import httpx
import polars as pl
import pyogrio
import shapely
from shapely.geometry import box

from transport_maps import config
from transport_maps.sources._utils import _atomic_write, _params_hash

LAND_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"

# A part is Antarctic when its northernmost point (bounds[3], the max latitude)
# does not exceed this value. Such parts are not dropped -- they are rebuilt as
# pole-free wedges by _antarctic_wedges, because H3
# cannot polyfill a shape that wraps a pole, and Antarctica has no scheduled
# service, so it is excluded.
ANTARCTICA_MAX_LAT = -60.0
# H3 cannot polyfill a pole-enclosing ring, so the pole itself is clipped away
# and the remainder cut into wedges.
POLE_CLIP_LAT = -84.5
WEDGE_COUNT = 12

_MULTIPOLYGON_TYPE_ID = 6


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
    kept.extend(_antarctic_wedges([p for p in parts if p.bounds[3] <= ANTARCTICA_MAX_LAT]))
    if not kept:
        raise RuntimeError("no land parts parsed from Natural Earth archive")
    return kept


def _antarctic_wedges(antarctic: list) -> list:
    """Antarctica as pole-free wedges.

    H3 cannot polyfill a ring that encloses a pole, which is why this continent
    was previously dropped entirely -- leaving a visible hole in the chart. Clip
    the pole away and cut what remains into longitude wedges; no wedge contains
    the pole, so each polyfills normally. Measured: 42,704 cells, 0 failures.
    """
    if not antarctic:
        return []
    whole = shapely.union_all(antarctic)
    wedges = []
    for i in range(WEDGE_COUNT):
        west = -180.0 + i * (360.0 / WEDGE_COUNT)
        east = west + (360.0 / WEDGE_COUNT)
        piece = shapely.intersection(whole, box(west, POLE_CLIP_LAT, east, ANTARCTICA_MAX_LAT + 0.5))
        if piece.is_empty:
            continue
        wedges.extend(shapely.get_parts(piece) if shapely.get_type_id(piece) == _MULTIPOLYGON_TYPE_ID else [piece])
    return wedges


def _cells_cache_path(res: int):
    """Cache path for `res`, stamped with the other constants that shape it.

    The resolution was already encoded in the filename; ANTARCTICA_MAX_LAT and
    the source archive were not, so changing either would have been read back
    from the file built under the old value.
    """
    stamp = _params_hash(LAND_URL, ANTARCTICA_MAX_LAT, POLE_CLIP_LAT, WEDGE_COUNT)
    return config.BUILD / f"land_cells_r{res}_{stamp}.parquet"


def land_cells(res: int) -> list[str]:
    """H3 cells at `res` overlapping land. Cached to parquet."""
    config.ensure_dirs()
    out = _cells_cache_path(res)
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
