"""Per-cell minutes -> isochrone band polygons, drawn as hexagons.

How the bands fit together
--------------------------
Band k is emitted as the CUMULATIVE region reached within its upper edge,
minus the cells that sit safely inside the previous band -- so it covers its
own cells plus a one-cell rim of everything faster. Neighbouring bands
overlap by that rim, the page draws the faster band on top (`fill-sort-key`
in web/app.js), and the visible boundary between k-1 and k is always k-1's
own outer edge.

The overlap is the whole point, and it is why nothing here is smoothed.
Rounding the corners was tried and removed (see `_dissolve` below and the
design policy in CLAUDE.md): it moves a boundary by up to a quarter of a hex
edge -- about 0.9 km at resolution 6, 0.35 km at 7 -- and moves it differently
for each polygon it is applied to, so where three bands met, two independently
rounded curves diverged and left a triangular hole. With 37 bands, most of them one
cell wide, those junctions were everywhere and the map read as hexagons with
gaps between them. A one-cell rim (2.4 km at the least, where the grid is
refined to resolution 7; 6.5 km on the base grid) puts the hidden edge far
beyond anything smoothing can reach, so a gap is geometrically impossible
rather than merely unlikely. `validate.check_bands_cover` checks that promise
on the emitted geometry.

The bands are NOT clipped to the coast here. They run one cell into the sea
(contour/grid.py adds the fringe) and the static water layer drawn above them
cuts them back to the real shoreline, at whatever precision that layer
carries -- far beyond what clipping every origin against a land mask could
afford, and independent of it.
"""

import bisect

import h3
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon, box
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


def cell_flags(cells) -> tuple[np.ndarray, np.ndarray]:
    """(wraps, resolution) per cell: what `_dissolve` needs to know of each.

    Both are properties of the cell alone, so a build computes them ONCE for
    its cell universes (`precompute_flags`) instead of once per cell per band
    per origin. A cell sits in every band from its own to the slowest within
    its rim, so the dissolves of one origin asked ~29 million times about ~14
    million cells: two boundary tests each, about 115 s of the ~480 s an
    origin took (PR-2), to find the few thousand cells on Earth that wrap.
    """
    wraps = np.fromiter((_crosses_antimeridian(c) for c in cells), dtype=bool, count=len(cells))
    res = np.fromiter((h3.get_resolution(c) for c in cells), dtype=np.int8, count=len(cells))
    return wraps, res


def precompute_flags(idx, grid) -> dict:
    """`cell_flags` of the native cells and of the render grid, for
    `band_feature_collection(flags=...)`. `grid` is the
    `contour.grid.universe(...)` the build hands every origin; the split
    parents the native level paints are its leading base cells."""
    return {"native": cell_flags(idx.cells), "base": cell_flags(grid[0])}


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


def _lnglat_ring(loop):
    """One h3 loop of (lat, lng) as a shapely ring of (lng, lat), closed."""
    return shapely.linearrings(np.asarray(loop, dtype=float)[:, ::-1])


def _h3shape_parts(h3shape) -> list:
    """The polygons of an h3 shape, in its order, as shapely objects.

    The same rings `shapely.get_parts(shape(h3.h3shape_to_geo(s)))` gives --
    lng/lat, closed, outer ring then holes -- built from numpy arrays instead.
    That route rebuilt every point as a Python tuple twice (h3's
    `_swap_latlng`, then shapely parsing them back), and for a native-level
    band of millions of vertices it was ~28% of an origin (py-spy, Seoul,
    2026-10-07). tests/contour/test_bands.py holds the two byte for byte.
    """
    polys = [h3shape] if isinstance(h3shape, h3.LatLngPoly) else list(h3shape)
    return [shapely.polygons(_lnglat_ring(p.outer), holes=[_lnglat_ring(h) for h in p.holes] or None)
            for p in polys]


def _dissolve(cells: list[str], wraps: np.ndarray | None = None,
              res: np.ndarray | None = None):
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

    `wraps` and `res` are `cell_flags(cells)`, passed in by a caller that has
    them precomputed; left out, they are computed here. Either way the parts
    come out in the order they always did -- resolution groups in order of
    first appearance, each in input order, then the wrapping cells -- so the
    emitted GeoJSON is the same byte for byte (tests/contour/test_bands.py
    compares it against the per-cell version this replaced).
    """
    if wraps is None or res is None:
        wraps, res = cell_flags(cells)
    cells_arr = np.asarray(cells, dtype=object)
    normal, normal_res = cells_arr[~wraps], res[~wraps]
    wrapping = cells_arr[wraps].tolist()
    parts = []
    found, first = np.unique(normal_res, return_index=True)
    for r in found[np.argsort(first)]:
        group = normal[normal_res == r].tolist()
        parts.extend(_h3shape_parts(h3.cells_to_h3shape(group, tight=True)))
    for cell in wrapping:
        parts.extend(shapely.get_parts(shapely.make_valid(unary_union(_split_at_antimeridian(cell)))))
    parts = [g for g in parts if g.geom_type == "Polygon" and not g.is_empty]
    if not parts:
        return None
    # The resolution groups (and a split cell's parent under its children)
    # overlap along their seams and are NOT unioned: a GEOS overlay of two
    # hundred-thousand-vertex multipolygons per band cost minutes per origin,
    # and neither the renderer nor tippecanoe needs it -- overlapping parts of
    # one feature paint the same colour twice.
    return shapely.multipolygons(parts) if len(parts) > 1 else parts[0]


# Levels of detail. tippecanoe simplifies in TILE space, so its tolerance at
# low zoom is tens of kilometres: 10 km at zoom 3, 20 km at zoom 2, 39 km at
# zoom 1. That is more than the rim that keeps neighbouring bands overlapping,
# so hairlines opened between bands at those zooms, and more than the hex
# fringe along the coast, which Douglas-Peucker turned into a sawtooth of
# black teeth. Each band is therefore emitted once per level, and
# tippecanoe's per-feature `tippecanoe.minzoom/maxzoom` keeps the copies
# apart. Margins are in whole cells (a resolution-6 base cell is 6.5 km
# across, a resolution-7 fine one 2.4 km, a resolution-4 parent 45 km; h3
# 4.5.0 figures); nothing is smoothed, so a margin is exactly its cell count.
#
#   z7+  : the native, mixed-resolution grid, two-cell rim (4.8 km at least,
#          against 0.6 km at zoom 7).
#   z5-6 : the base grid, one-cell rim and one ring out to sea (6.5 km
#          against 2.4 km at zoom 5).
#   z3-4 : the base grid, three-cell rim and three rings (19 km against 10).
#   z0-2 : resolution-4 parents, fully cumulative (overlap is free at world
#          scale), two rings at that resolution (two 45 km cells against 39
#          at zoom 1).
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
        # The shapely geometry itself, not its `mapping()`: as nested tuples
        # of Python floats a coordinate costs 128 bytes (measured on the
        # Taveuni fixture in tests/emit/test_tiles.py) against GEOS's 16, and
        # one origin's bands were ~3-4 GB of it, most of a worker's footprint
        # (PR-1), which `check_bands_cover` then parsed back into shapely.
        # tiles.write_pmtiles maps one feature at a time as it writes (R1).
        "geometry": geometry,
    }


def _slowest_within(band: np.ndarray, rows: np.ndarray, cols: np.ndarray, rim: int) -> np.ndarray:
    """For each cell, the slowest band within `rim` steps over the edge list
    (excluding the cell itself). Band-independent, so computed once per level:
    a cell is safely inside "everything faster than band k" exactly when its
    own band and this value are both below k. Neighbours are an edge list, so
    a cell may have any number of them."""
    slowest = np.full(len(band), -1, dtype=np.int64)
    np.maximum.at(slowest, rows, band[cols])
    for _ in range(rim - 1):
        wider = slowest.copy()
        np.maximum.at(wider, rows, slowest[cols])
        slowest = wider
    return slowest


def _edges_from_table(nb: np.ndarray, sub: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A neighbour table restricted to `sub`, as an edge list."""
    keep = (nb >= 0) & sub[np.maximum(nb, 0)] & sub[:, None]
    rows = np.repeat(np.arange(len(nb)), nb.shape[1])[keep.ravel()]
    cols = nb.ravel()[keep.ravel()]
    return rows.astype(np.int64), cols.astype(np.int64)


def _base_features(lod: dict, cells_arr, nb, ring, band, flags) -> list[dict]:
    """Base-grid bands with a rim of `lod['rim']` cells over the faster ones."""
    sub = ring <= lod["rings"]
    rows, cols = _edges_from_table(nb, sub)
    slowest = _slowest_within(band, rows, cols, lod["rim"])
    wraps, res = flags
    out = []
    for k in np.unique(band[sub]).tolist():
        keep = sub & (band <= k) & ~((band <= k - 1) & (slowest <= k - 1))
        geometry = _dissolve(cells_arr[keep].tolist(), wraps[keep], res[keep])
        if geometry is not None and not geometry.is_empty:
            out.append(_feature(k, geometry, lod))
    return out


def _native_features(lod: dict, idx, band: np.ndarray, native, flags, base_flags) -> list[dict]:
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
    slowest = _slowest_within(band, rows, cols, lod["rim"])
    wraps, res = flags
    out = []
    for k in np.unique(band).tolist():
        keep = (band <= k) & ~((band <= k - 1) & (slowest <= k - 1))
        cells = cells_arr[keep].tolist()
        cell_wraps, cell_res = wraps[keep], res[keep]
        if fine.any():
            painted = split_parents[parent_band[split_parents] == k]
            cells += base_arr[painted].tolist()
            # Base cells lead the render grid, so their flags are its flags.
            cell_wraps = np.concatenate([cell_wraps, base_flags[0][painted]])
            cell_res = np.concatenate([cell_res, base_flags[1][painted]])
        geometry = _dissolve(cells, cell_wraps, cell_res)
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
    # Tens of thousands of parents, flagged once here rather than once per
    # band they are dissolved in.
    wraps, res = cell_flags(names.tolist())
    out = []
    for k in np.unique(band).tolist():
        geometry = _dissolve(names[pb <= k].tolist(), wraps[pb <= k], res[pb <= k])
        if geometry is not None and not geometry.is_empty:
            out.append(_feature(k, geometry, lod))
    return out


def _fill_rings(minutes: np.ndarray, nb: np.ndarray, ring: np.ndarray) -> None:
    """Each sea ring takes the fastest cell of the ring inside it, in place."""
    for r in range(1, int(ring.max()) + 1 if len(ring) else 1):
        sel = np.flatnonzero(ring == r)
        nbs = nb[sel]
        minutes[sel] = np.where(nbs >= 0, minutes[np.maximum(nbs, 0)], np.inf).min(axis=1)


def band_feature_collection(idx, cell_minutes: np.ndarray, grid=None, native=None,
                            skip_native: bool = False, flags: dict | None = None) -> dict:
    """GeoJSON FeatureCollection: one feature per occupied band per level of
    detail (see LODS), each level in ascending band order with unreachable
    land last.

    `skip_native` drops the zoom-7+ level, the mixed-resolution one. It is
    three quarters of every archive (Seoul: 22.1 of 29.4 MB at z7-z8), and the
    exclusion variants ("avoid flights" and the rest) are built without it so
    three of them fit on the web host beside the full set; the page enlarges
    their zoom-6 tiles instead.

    `grid` is `contour.grid.universe(idx.base_cells)` and `native` is
    `contour.grid.native_edges(idx)`; the build computes both once in the
    parent process and hands them to every forked worker. `flags` is
    `precompute_flags(idx, grid)`, likewise once per build (R2).
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
    flags = flags if flags is not None else precompute_flags(idx, (cells6, nb6, ring6))
    # A mask from another universe would not fail anywhere: it would send the
    # wrong cells through the planar dissolve, which is how a wrapping cell
    # becomes a polygon spanning the globe.
    if len(flags["native"][0]) != idx.n_cells or len(flags["base"][0]) != len(cells6):
        raise ValueError("cell flags do not match the cell universe")

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
            if not skip_native:
                features += _native_features(lod, idx, band, native,
                                             flags["native"], flags["base"])
        elif lod["kind"] == "base":
            features += _base_features(lod, cells6_arr, nb6, ring6, base_band, flags["base"])
        else:
            features += _coarse_features(lod, cells6_arr, base_band)
    return {"type": "FeatureCollection", "features": features}
