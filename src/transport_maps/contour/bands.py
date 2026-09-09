"""Per-cell minutes -> smoothed isochrone band polygons.

How the bands fit together
--------------------------
Band k is emitted as the CUMULATIVE region reached within its upper edge,
minus the cells that sit safely inside the previous band -- so it covers its
own cells plus a one-cell rim of everything faster. Neighbouring bands
overlap by that rim, the page draws the faster band on top (`fill-sort-key`
in web/app.js), and the visible boundary between k-1 and k is always k-1's
own outer edge.

The overlap is the whole point. Smoothing moves a boundary by up to a quarter
of a hex edge (about 2 km at resolution 5), and moves it differently for each
polygon it is applied to: where three bands met, two independently rounded
curves diverged and left a triangular hole. With 37 bands, most of them one
cell wide, those junctions were everywhere and the map read as hexagons with
gaps between them. A one-cell rim (7 km at the least) puts the hidden edge far
beyond anything smoothing can reach, so a gap is geometrically impossible
rather than merely unlikely. `validate.check_bands_cover` checks that promise
on the emitted geometry.

The bands are NOT clipped to the coast here. They run one cell into the sea
(contour/grid.py adds the fringe) and the static water layer drawn above them
cuts them back to the real shoreline, at whatever precision that layer
carries -- far beyond what clipping 157 origins against a land mask could
afford, and independent of it.
"""

import bisect

import h3
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union

from transport_maps import config

UNREACHABLE_BAND = -1


def band_of(minutes: float) -> int:
    """Band index for a time. Values above the last edge fall in the open band."""
    if not np.isfinite(minutes):
        return UNREACHABLE_BAND
    return bisect.bisect_left(config.BAND_EDGES_MIN, minutes)


def band_indices(minutes: np.ndarray) -> np.ndarray:
    """Vectorised `band_of`, except that unreachable comes out as one past the
    open band so that "everything up to band k" is a plain `<=` comparison."""
    m = np.asarray(minutes, dtype=float)
    edges = np.asarray(config.BAND_EDGES_MIN, dtype=float)
    k = np.searchsorted(edges, m, side="left")
    return np.where(np.isfinite(m), k, len(edges) + 1).astype(np.int64)


ANTIMERIDIAN_SPAN_DEG = 180.0


def _crosses_antimeridian(cell: str) -> bool:
    lons = [lon for _lat, lon in h3.cell_to_boundary(cell)]
    return max(lons) - min(lons) > ANTIMERIDIAN_SPAN_DEG


def _split_at_antimeridian(cell: str) -> list:
    """A cell straddling +/-180 as one or two polygons inside [-180, 180].

    In planar lat/lon a wrapping cell's ring reads as spanning the globe
    backwards: measured on a real Fiji-area cell, the naive polygon is INVALID
    with area 27.37 deg^2 against a true 0.0202. With 26 such cells in Seoul's
    band 9 that injected roughly 711 deg^2 of phantom area, which is what made
    bands appear to overlap. Shift negative longitudes east into a continuous
    frame, clip either side of 180, then translate the eastern piece back.
    """
    boundary = h3.cell_to_boundary(cell)
    lats = [lat for lat, _lon in boundary]
    unwrapped = [lon + 360.0 if lon < 0 else lon for _lat, lon in boundary]
    ring = Polygon(zip(unwrapped, lats))
    left = ring.intersection(box(-180.0, -90.0, 180.0, 90.0))
    right = affinity.translate(
        ring.intersection(box(180.0, -90.0, 540.0, 90.0)), xoff=-360.0
    )
    return [part for part in (left, right) if not part.is_empty]


def _polygonal(geom):
    """Keep only the areal parts of a geometry.

    `make_valid` on a self-touching ring returns a GeometryCollection: the
    polygons plus the zero-width spurs it had to cut out as bare LineStrings.
    Passing that on emits a GeoJSON GeometryCollection for a band -- a shape
    with dangling lines in it -- so the non-areal debris is dropped here.
    """
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    parts = [g for g in shapely.get_parts(geom)
             if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
    if not parts:
        return shapely.Polygon()
    return shapely.make_valid(shapely.union_all(parts))


def _dissolve(cells: list[str]):
    """Dissolve one band's cells, handling the antimeridian.

    h3.cells_to_h3shape is EXACT and fast even at scale -- measured against a
    per-cell shapely union on Seoul's bands 7, 8 and 9 (202,482 / 111,742 /
    69,732 cells, hundreds of disconnected components each), the symmetric
    difference was 0.0000 in all three once wrapping cells were removed. Do NOT
    replace it with a per-cell union: that is far slower AND still wrong at the
    antimeridian. It wants one resolution at a time; the native level mixes
    two, so they are dissolved separately and unioned.

    Hexagons are emitted as hexagons. Rounding their corners was tried and is
    what opened gaps between bands: it moves every boundary, differently for
    each polygon it is applied to.
    """
    normal = [c for c in cells if not _crosses_antimeridian(c)]
    wrapping = [c for c in cells if _crosses_antimeridian(c)]
    geoms = []
    by_res: dict[int, list[str]] = {}
    for c in normal:
        by_res.setdefault(h3.get_resolution(c), []).append(c)
    for group in by_res.values():
        geoms.append(shape(h3.h3shape_to_geo(h3.cells_to_h3shape(group, tight=True))))
    for cell in wrapping:
        geoms.extend(_split_at_antimeridian(cell))
    if not geoms:
        return None
    return _polygonal(shapely.make_valid(unary_union(geoms)))


# Levels of detail. tippecanoe simplifies in TILE space, so its tolerance at
# low zoom is tens of kilometres: 10 km at zoom 3, 20 km at zoom 2, 39 km at
# zoom 1. That is more than the rim that keeps neighbouring bands overlapping,
# so hairlines opened between bands at those zooms, and more than the hex
# fringe along the coast, which Douglas-Peucker turned into a sawtooth of
# black teeth. Each band is therefore emitted once per level, and
# tippecanoe's per-feature `tippecanoe.minzoom/maxzoom` keeps the copies
# apart. Margins are in whole cells (a base cell is 5.6 km across, a fine one
# 2.1 km); nothing is smoothed, so a margin is exactly its cell count.
#
#   z7+  : the native, mixed-resolution grid, two-cell rim (4 km at least,
#          against 0.6 km at zoom 7).
#   z5-6 : the base grid, one-cell rim and one ring out to sea (5.6 km
#          against 2.4 km at zoom 5).
#   z3-4 : the base grid, three-cell rim and three rings (17 km against 10).
#   z0-2 : resolution-4 parents, fully cumulative (overlap is free at world
#          scale), two rings at that resolution (45 km against 39 at zoom 1).
#
# A sea margin bleeds across a strait onto the far shore by up to its own
# width, one to three pixels at these zooms; the water layer hides the rest.
LODS = (
    {"minzoom": 7, "maxzoom": None, "kind": "native", "rim": 2},
    {"minzoom": 5, "maxzoom": 6, "kind": "base", "rim": 1, "rings": 1},
    {"minzoom": 3, "maxzoom": 4, "kind": "base", "rim": 3, "rings": 3},
    {"minzoom": 0, "maxzoom": 2, "kind": "coarse", "res": 4, "rings": 2},
)


def lod_features(feature_collection: dict, lod: int) -> list[dict]:
    """The features emitted for one level of detail, in emission order."""
    minzoom = LODS[lod]["minzoom"]
    return [f for f in feature_collection["features"]
            if f.get("tippecanoe", {}).get("minzoom") == minzoom]


def _feature(k: int, geometry, lod: dict) -> dict:
    open_band = len(config.BAND_EDGES_MIN)
    emitted = UNREACHABLE_BAND if k == open_band + 1 else int(k)
    zoom = {"minzoom": lod["minzoom"]}
    if lod["maxzoom"] is not None:
        zoom["maxzoom"] = lod["maxzoom"]
    return {
        "type": "Feature",
        "tippecanoe": zoom,
        "properties": {
            "band": emitted,
            # None for the open band AND for unreachable land: band -1 would
            # otherwise index BAND_EDGES_MIN from the end and claim the
            # unreachable cells are inside the last edge.
            "max_minutes": (config.BAND_EDGES_MIN[emitted]
                            if 0 <= emitted < open_band else None),
        },
        "geometry": mapping(geometry),
    }


def _interior(band: np.ndarray, k: int, rows: np.ndarray, cols: np.ndarray, rim: int) -> np.ndarray:
    """Cells safely inside "everything faster than band k": their own band is
    faster and so is every neighbour's, `rim` cells deep. Neighbours are an
    edge list, so a cell may have any number of them."""
    slowest = np.full(len(band), -1, dtype=np.int64)
    np.maximum.at(slowest, rows, band[cols])
    interior = (band <= k - 1) & (slowest <= k - 1)
    for _ in range(rim - 1):
        bad = np.zeros(len(band), dtype=bool)
        np.logical_or.at(bad, rows, ~interior[cols])
        interior &= ~bad
    return interior


def _edges_from_table(nb: np.ndarray, sub: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A neighbour table restricted to `sub`, as an edge list."""
    keep = (nb >= 0) & sub[np.maximum(nb, 0)] & sub[:, None]
    rows = np.repeat(np.arange(len(nb)), nb.shape[1])[keep.ravel()]
    cols = nb.ravel()[keep.ravel()]
    return rows.astype(np.int64), cols.astype(np.int64)


def _base_features(lod: dict, cells_arr, nb, ring, band) -> list[dict]:
    """Base-grid bands with a rim of `lod['rim']` cells over the faster ones."""
    sub = ring <= lod["rings"]
    rows, cols = _edges_from_table(nb, sub)
    out = []
    for k in np.unique(band[sub]).tolist():
        keep = sub & (band <= k) & ~_interior(band, k, rows, cols, lod["rim"])
        geometry = _dissolve(cells_arr[keep].tolist())
        if geometry is not None and not geometry.is_empty:
            out.append(_feature(k, geometry, lod))
    return out


def _native_features(lod: dict, idx, band: np.ndarray, native) -> list[dict]:
    """The mixed-resolution grid itself, rimmed, with each split base cell's
    hexagon underneath its children.

    Seven fine children do not tile their parent exactly -- the aggregate edge
    wanders about a child's width -- so where a split cell meets an unsplit
    one, slivers would show through. The parent hexagon, painted in the
    SLOWEST of its children's bands, sits beneath them (the page paints faster
    bands on top) and closes those slivers with the least wrong colour.
    """
    rows, cols, _complete = native
    cells_arr = np.array(idx.cells, dtype=object)
    fine_attr = getattr(idx, "fine", np.zeros(0, dtype=bool))
    fine = fine_attr if len(fine_attr) == len(idx.cells) else np.zeros(len(idx.cells), dtype=bool)
    if fine.any():
        split_parents = np.unique(idx.base_index[fine])
        parent_band = np.full(len(idx.base_cells), -1, dtype=np.int64)
        np.maximum.at(parent_band, idx.base_index[fine], band[fine])
        base_arr = np.array(idx.base_cells, dtype=object)
    out = []
    for k in np.unique(band).tolist():
        keep = (band <= k) & ~_interior(band, k, rows, cols, lod["rim"])
        cells = cells_arr[keep].tolist()
        if fine.any():
            cells += base_arr[split_parents[parent_band[split_parents] == k]].tolist()
        geometry = _dissolve(cells)
        if geometry is not None and not geometry.is_empty:
            out.append(_feature(k, geometry, lod))
    return out


def _coarse_features(lod: dict, cells_arr, band) -> list[dict]:
    """Cumulative bands over coarser parents, grown `lod['rings']` rings out at
    that resolution: a parent is within edge k when any child is, and a sea
    ring takes the fastest parent inside it."""
    parents = np.array([h3.cell_to_parent(c, lod["res"]) for c in cells_arr], dtype=object)
    uniq, inverse = np.unique(parents, return_inverse=True)
    fastest = np.full(len(uniq), np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(fastest, inverse, band)
    pband = {c: int(b) for c, b in zip(uniq.tolist(), fastest.tolist())}
    frontier = list(pband)
    for _ in range(lod["rings"]):
        grown: dict[str, int] = {}
        for c in frontier:
            for n in h3.grid_ring(c, 1):
                if n not in pband:
                    grown[n] = min(grown.get(n, np.iinfo(np.int64).max), pband[c])
        pband.update(grown)
        frontier = list(grown)
    names = np.array(list(pband), dtype=object)
    pb = np.array(list(pband.values()), dtype=np.int64)
    out = []
    for k in np.unique(band).tolist():
        geometry = _dissolve(names[pb <= k].tolist())
        if geometry is not None and not geometry.is_empty:
            out.append(_feature(k, geometry, lod))
    return out


def _fill_rings(minutes: np.ndarray, nb: np.ndarray, ring: np.ndarray) -> None:
    """Each sea ring takes the fastest cell of the ring inside it, in place."""
    for r in range(1, int(ring.max()) + 1 if len(ring) else 1):
        sel = np.flatnonzero(ring == r)
        nbs = nb[sel]
        minutes[sel] = np.where(nbs >= 0, minutes[np.maximum(nbs, 0)], np.inf).min(axis=1)


def band_feature_collection(idx, cell_minutes: np.ndarray, grid=None, native=None) -> dict:
    """GeoJSON FeatureCollection: one feature per occupied band per level of
    detail (see LODS), each level in ascending band order with unreachable
    land last.

    `grid` is `contour.grid.universe(idx.base_cells)` and `native` is
    `contour.grid.native_edges(idx)`; the build computes both once in the
    parent process and hands them to every forked worker.
    """
    if len(cell_minutes) < idx.n_cells:
        raise ValueError("cell_minutes shorter than the cell universe")
    from transport_maps.contour import grid as grid_mod

    base_cells_attr = getattr(idx, "base_cells", [])
    refined = len(base_cells_attr) > 0
    base_cells = base_cells_attr if refined else list(idx.cells)
    cells6, nb6, ring6 = grid if grid is not None else grid_mod.universe(base_cells)
    if cells6[: len(base_cells)] != list(base_cells):
        raise ValueError("render grid does not match the base cell universe")
    native = native if native is not None else grid_mod.native_edges(idx)

    minutes = np.asarray(cell_minutes[: idx.n_cells], dtype=float)
    band = band_indices(minutes)

    # The base grid carries the fastest of each cell's children, then its
    # sea rings, then bands.
    base_minutes = np.full(len(cells6), np.inf)
    if refined:
        np.minimum.at(base_minutes, idx.base_index, minutes)
    else:
        base_minutes[: len(base_cells)] = minutes
    _fill_rings(base_minutes, nb6, ring6)
    base_band = band_indices(base_minutes)
    cells6_arr = np.array(cells6, dtype=object)

    features: list[dict] = []
    for lod in LODS:
        if lod["kind"] == "native":
            features += _native_features(lod, idx, band, native)
        elif lod["kind"] == "base":
            features += _base_features(lod, cells6_arr, nb6, ring6, base_band)
        else:
            features += _coarse_features(lod, cells6_arr, base_band)
    return {"type": "FeatureCollection", "features": features}
