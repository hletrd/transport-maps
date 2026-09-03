"""Natural Earth land polygons -> the H3 cell universe."""

import pathlib

import h3
import httpx
import polars as pl
import pyogrio
import shapely

from transport_maps import config

LAND_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"

# Parts reaching below this latitude are Antarctic. H3 cannot polyfill a shape
# containing a pole, and Antarctica has no scheduled service, so it is excluded.
ANTARCTICA_MAX_LAT = -60.0

_MULTIPOLYGON_TYPE_ID = 6


def _download() -> pathlib.Path:
    config.ensure_dirs()
    cached = config.CACHE / "ne_10m_land.zip"
    if not cached.exists():
        r = httpx.get(LAND_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        cached.write_bytes(r.content)
    return cached


def _land_parts() -> list[shapely.Geometry]:
    """Single polygons covering land, excluding Antarctica."""
    path = _download().resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    geom_column = next(c for c in table.schema.names if "geom" in c.lower())
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
    failures: list[tuple[float, ...]] = []
    for poly in _land_parts():
        try:
            shape = h3.geo_to_h3shape(poly)
            cells.update(h3.h3shape_to_cells_experimental(shape, res, contain="overlap"))
        except Exception:  # noqa: BLE001 -- any polyfill failure must be surfaced, not just H3FailedError
            failures.append(poly.bounds)

    if failures:
        raise RuntimeError(f"{len(failures)} land parts failed to cellify: {failures[:5]}")

    ordered = sorted(cells)
    pl.DataFrame({"cell": ordered}).write_parquet(out)
    return ordered
