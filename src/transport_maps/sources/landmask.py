"""Natural Earth land polygons -> the H3 cell universe."""

import pathlib

import h3
import polars as pl
import pyogrio
import shapely
from shapely import STRtree
from shapely.geometry import box

from transport_maps import config
from transport_maps.sources import _fetch
from transport_maps.sources._utils import _atomic_write, _params_hash

LAND_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
# Natural Earth keeps floating ice off the land layer, so ne_10m_land has
# Antarctica with the Ross and Ronne shelves cut out of it -- the map answered
# "not on land" over both. They are permanent traversable surface (McMurdo's
# runway is on one), so they are unioned in.
# ne_10m_land treats inland water as land: the Great Lakes, the Caspian and
# Lake Victoria all rendered as solid ground with travel times painted across
# them. The lakes layer is subtracted so they read as water.
LAKES_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes.zip"
ICE_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_physical/"
    "ne_10m_antarctic_ice_shelves_polys.zip"
)

# A part is Antarctic when its northernmost point (bounds[3], the max latitude)
# does not exceed this value. Such parts are not dropped -- they are rebuilt as
# pole-free wedges by _antarctic_wedges, because H3
# cannot polyfill a shape that wraps a pole, and Antarctica has no scheduled
# service, so it is excluded.
ANTARCTICA_MAX_LAT = -60.0
# H3 cannot polyfill a pole-enclosing ring, so the pole itself is clipped away
# and the remainder cut into wedges.
# Clipping at -84.5 left everything beyond it -- the Ross Ice Shelf, the South
# Pole itself -- with no cell at all, so the map answered "not on land" there.
# -89.9 keeps the wedge a valid lat/lon polygon (the pole is a singularity in
# this projection) while covering all but a ~11 km cap, which _pole_cells adds
# explicitly.
POLE_CLIP_LAT = -89.9
WEDGE_COUNT = 12
# Part of the land-cell cache stamp: which polyfill produced the universe.
POLYFILL_METHOD = "pole-cells+shelves-lakes; h3shape_to_cells_experimental(overlap)"

_MULTIPOLYGON_TYPE_ID = 6


LAND_ZIP = "ne_10m_land.zip"
ICE_ZIP = "ne_10m_antarctic_ice_shelves_polys.zip"
LAKES_ZIP = "ne_10m_lakes.zip"


def _download(url: str = LAND_URL, name: str = LAND_ZIP) -> pathlib.Path:
    """One Natural Earth archive, checked against the upstream once per build (G2)."""
    config.ensure_dirs()
    return _fetch.fetch(url, config.CACHE / name).path


def _archives() -> list[tuple[str, str]]:
    """(url, cache name) of every archive the land universe is cut from."""
    return [(LAND_URL, LAND_ZIP), (ICE_URL, ICE_ZIP), (LAKES_URL, LAKES_ZIP)]


def _sources() -> list[str]:
    """The sha256 of each archive in `_archives()`, after checking each one.

    What the land-cell and landmass keys are stamped with: the URLs named
    where the archives came from, not which release of them was read, and
    Natural Earth republishes under the same URL.
    """
    config.ensure_dirs()
    return [_fetch.fetch(url, config.CACHE / name).sha256 for url, name in _archives()]


def _known_sources() -> list[str] | None:
    """`_sources()` as recorded on disk, with no request: None unless every
    archive has a sidecar matching it. For tools that must find the land
    cells without building them (scripts/expand_origins.py)."""
    found = [_fetch.peek(config.CACHE / name) for _url, name in _archives()]
    return None if None in found else found


def _ice_shelf_parts() -> list[shapely.Geometry]:
    """Antarctic ice shelves, which the land layer omits."""
    path = _download(ICE_URL, ICE_ZIP).resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    geom_column = next(c for c in table.schema.names if "geom" in c.lower())
    geoms = shapely.from_wkb(table.column(geom_column).to_pylist())
    return [g for g in geoms if g is not None and not g.is_empty]


def _lake_union() -> shapely.Geometry:
    path = _download(LAKES_URL, LAKES_ZIP).resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    geom_column = next(c for c in table.schema.names if "geom" in c.lower())
    geoms = [g for g in shapely.from_wkb(table.column(geom_column).to_pylist())
             if g is not None and not g.is_empty]
    return shapely.make_valid(shapely.union_all(geoms))


def _without_lakes(parts: list[shapely.Geometry]) -> list[shapely.Geometry]:
    """Cut inland water out of the land parts that actually touch it.

    Only parts whose bounds meet a lake are differenced; the other ~6,000
    are returned untouched, which keeps this to a few seconds.
    """
    lakes = _lake_union()
    tree = STRtree(list(shapely.get_parts(lakes)))
    out: list[shapely.Geometry] = []
    for part in parts:
        if len(tree.query(part)) == 0:
            out.append(part)
            continue
        cut = shapely.make_valid(shapely.difference(part, lakes))
        if cut.geom_type == "MultiPolygon":
            out.extend(g for g in shapely.get_parts(cut) if not g.is_empty)
        elif cut.geom_type == "Polygon" and not cut.is_empty:
            out.append(cut)
        else:
            out.extend(g for g in shapely.get_parts(cut)
                       if g.geom_type == "Polygon" and not g.is_empty)
    return out


def _land_parts() -> list[shapely.Geometry]:
    """Single polygons covering land, excluding Antarctica and inland water."""
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

    antarctic = [p for p in parts if p.bounds[3] <= ANTARCTICA_MAX_LAT]
    # The shelves are wedged with the rest of Antarctica, so they inherit the
    # same pole handling instead of needing their own.
    antarctic.extend(
        q for g in _ice_shelf_parts()
        for q in (shapely.get_parts(g)
                  if shapely.get_type_id(g) == _MULTIPOLYGON_TYPE_ID else [g])
    )
    kept = _without_lakes([p for p in parts if p.bounds[3] > ANTARCTICA_MAX_LAT])
    kept.extend(_antarctic_wedges(antarctic))
    if not kept:
        raise RuntimeError("no land parts parsed from Natural Earth archive")
    return kept


def _pole_cells(res: int) -> set[str]:
    """The cell over the South Pole and its ring.

    A lat/lon wedge cannot close over the pole, so the last few kilometres are
    added by cell id instead of by geometry.
    """
    import h3

    centre = h3.latlng_to_cell(-90.0, 0.0, res)
    return set(h3.grid_disk(centre, 2))


def _antarctic_wedges(antarctic: list) -> list:
    """Antarctica as pole-free wedges.

    H3 cannot polyfill a ring that encloses a pole, which is why this continent
    was previously dropped entirely -- leaving a visible hole in the chart. Clip
    the pole away and cut what remains into longitude wedges; no wedge contains
    the pole, so each polyfills normally. Measured 2026-10-02 at res 6 on the
    current land_cells stamp: 363,488 cells carry ANTARCTICA_LANDMASS, 8.9 % of
    the 4,091,715. The 42,704 that stood here was measured on an earlier res-5
    universe and counts nothing the build now makes.
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


def _cells_cache_path(res: int, sources: list[str]):
    """Cache path for `res`, stamped with the other constants that shape it
    and with `sources`, the archives' hashes (`_sources()`).

    The resolution was already encoded in the filename; ANTARCTICA_MAX_LAT and
    the source archive were not, so changing either would have been read back
    from the file built under the old value. The URLs were, but a URL is not a
    release: a new Natural Earth archive under the same name read back the
    cells cut from the old one (G2).
    """
    stamp = _params_hash(LAND_URL, ICE_URL, LAKES_URL, ANTARCTICA_MAX_LAT,
                         POLE_CLIP_LAT, WEDGE_COUNT, POLYFILL_METHOD, sources)
    return config.BUILD / f"land_cells_r{res}_{stamp}.parquet"


# Landmass id shared by every Antarctic part. _land_parts cuts Antarctica into
# WEDGE_COUNT longitude wedges so H3 can polyfill it; the wedges are one
# continent, and numbering them apart would sever it along every wedge seam.
# Wedges are cut from parts routed by `bounds[3] <= ANTARCTICA_MAX_LAT`, and an
# intersection cannot extend past its input, so the same test finds every
# wedge; each non-Antarctic part's northern bound is strictly above it.
ANTARCTICA_LANDMASS = -1
# Bumped when the landmass assignment changes shape.
LANDMASS_VERSION = 1


def _landmasses_cache_path(res: int, sources: list[str]):
    """Stamped with the land universe it was computed over, so a change to
    anything that governs `land_cells` -- the land, ice or lake source, the
    Antarctic handling, the polyfill -- also misses here, and with the two
    constants that govern the assignment itself.

    A path helper rather than a key built inline, so the provenance table can
    mutation-test it; `countries.cell_country` builds its key inline and is a
    recorded gap for exactly that reason.
    """
    stamp = _params_hash(_cells_cache_path(res, sources).name, ANTARCTICA_LANDMASS,
                         LANDMASS_VERSION)
    return config.BUILD / f"land_landmasses_r{res}_{stamp}.parquet"


def land_cell_landmasses(res: int) -> list[tuple[int, ...]]:
    """For each cell of `land_cells(res)`, in that order, the land parts its
    hexagon touches.

    Computed by the SAME polyfill as land_cells -- h3's overlap fill, part by
    part -- so "touches part p" means exactly what made the cell land. Most
    cells touch one part. A cell straddling a strait narrower than itself
    touches both shores and so joins them: that is the resolution limit of
    graph/landmass, not an error in this function. The South Pole cells that
    _pole_cells adds by id touch no part and map to (), which graph/landmass
    reads as "never sever" -- they carry no evidence of water either way.
    """
    config.ensure_dirs()
    cells = land_cells(res)
    out = _landmasses_cache_path(res, _sources())
    if out.exists():
        return [tuple(p) for p in pl.read_parquet(out)["parts"].to_list()]

    pos = {c: i for i, c in enumerate(cells)}
    parts: list[set[int]] = [set() for _ in cells]
    for pid, poly in enumerate(_land_parts()):
        landmass = ANTARCTICA_LANDMASS if poly.bounds[3] <= ANTARCTICA_MAX_LAT else pid
        shape = h3.geo_to_h3shape(poly)
        for c in h3.h3shape_to_cells_experimental(shape, res, contain="overlap"):
            i = pos.get(c)
            if i is not None:
                parts[i].add(landmass)
    rows = [sorted(p) for p in parts]
    _atomic_write(out, lambda tmp: pl.DataFrame(
        {"cell": cells, "parts": rows},
        schema={"cell": pl.Utf8, "parts": pl.List(pl.Int32)}).write_parquet(tmp))
    return [tuple(p) for p in rows]


def land_cells(res: int) -> list[str]:
    """H3 cells at `res` overlapping land. Cached to parquet.

    The polyfill is h3's `h3shape_to_cells_experimental(contain="overlap")`:
    every cell that touches a land polygon, not only those whose centre is
    inside it, so islands and coastal spits smaller than a cell keep their
    cell. The function carries no API-stability promise in h3 4.x (its name
    says so); `tests/sources/test_landmask.py` pins the overlap behaviour on
    a cache-free run, and POLYFILL_METHOD names the method in the cache stamp
    so a change of method is a cache miss, not a silent reuse.
    """
    config.ensure_dirs()
    out = _cells_cache_path(res, _sources())
    if out.exists():
        return pl.read_parquet(out)["cell"].to_list()

    cells: set[str] = _pole_cells(res)
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
