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


# Chaikin corner-cutting. Two passes round a hexagon's 120-degree corners into
# something that reads as a contour rather than as tiling; a third is not worth
# the vertices. The isochrone surface is smooth -- the hexagons are only how it
# was sampled -- so rounding the sampling artefact is honest, not decorative.
SMOOTH_PASSES = 2
# Applied after smoothing, and deliberately LIGHT. Simplification pulls the
# rounded corners back onto the hexagon vertices they were cut from, so too
# much of it undoes the smoothing entirely. Measured on 20k cells, share of
# boundary turns near the hexagon's 60 degrees:
#
#   raw hexagons        10.4%   (median turn 37.9deg)
#   simplify 0.013      16.5%   (23.4deg)  <- WORSE than raw; the corners return
#   simplify 0.006      14.3%   (17.8deg)
#   simplify 0.003       6.8%   (11.2deg)  <- genuinely smooth
#   no simplification    5.5%   ( 8.2deg)
#
# tippecanoe simplifies again per zoom level, so trading smoothness for
# vertices here buys little: the tile it emits is re-simplified regardless.
SMOOTH_SIMPLIFY_DEG = 0.003


def _chaikin(ring: np.ndarray, passes: int = SMOOTH_PASSES) -> np.ndarray:
    """Corner-cut a closed ring, keeping it closed."""
    for _ in range(passes):
        p = ring[:-1]                      # drop the repeated last point
        q = np.roll(p, -1, axis=0)
        cut = np.empty((len(p) * 2, 2))
        cut[0::2] = 0.75 * p + 0.25 * q
        cut[1::2] = 0.25 * p + 0.75 * q
        ring = np.vstack([cut, cut[:1]])
    return ring


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


def _smooth(geom):
    """Round the hexagon corners off a dissolved band."""
    def ring(coords):
        a = np.asarray(coords)
        # Fewer than four distinct points is a sliver; smoothing collapses it.
        return a if len(a) < 5 else _chaikin(a)

    parts = []
    for poly in shapely.get_parts(geom) if geom.geom_type == "MultiPolygon" else [geom]:
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        parts.append(shapely.Polygon(
            ring(poly.exterior.coords),
            [ring(i.coords) for i in poly.interiors],
        ))
    if not parts:
        return geom
    out = _polygonal(shapely.make_valid(shapely.union_all(parts)))
    return _polygonal(shapely.make_valid(shapely.simplify(out, SMOOTH_SIMPLIFY_DEG)))


def _dissolve(cells: list[str]):
    """Dissolve one band's cells, handling the antimeridian.

    h3.cells_to_h3shape is EXACT and fast even at scale -- measured against a
    per-cell shapely union on Seoul's bands 7, 8 and 9 (202,482 / 111,742 /
    69,732 cells, hundreds of disconnected components each), the symmetric
    difference was 0.0000 in all three once wrapping cells were removed. Do NOT
    replace it with a per-cell union: that is far slower AND still wrong at the
    antimeridian.
    """
    normal = [c for c in cells if not _crosses_antimeridian(c)]
    wrapping = [c for c in cells if _crosses_antimeridian(c)]

    geoms = []
    if normal:
        geoms.append(shape(h3.h3shape_to_geo(h3.cells_to_h3shape(normal, tight=True))))
    for cell in wrapping:
        geoms.extend(_split_at_antimeridian(cell))

    if not geoms:
        return None
    merged = shapely.make_valid(unary_union(geoms))
    return _smooth(merged)


# Levels of detail. tippecanoe simplifies in TILE space, so its tolerance at
# low zoom is tens of kilometres: 10 km at zoom 3, 20 km at zoom 2, 39 km at
# zoom 1. That is more than the one-cell rim that keeps neighbouring bands
# overlapping, so hairlines opened between bands at those zooms, and more than
# the hex fringe along the coast, which Douglas-Peucker turned into a sawtooth
# of black teeth biting into every shore. Each band is therefore emitted once
# per level, and tippecanoe's per-feature `tippecanoe.minzoom/maxzoom` keeps
# the copies apart:
#
#   z5+  : resolution-5 cells, one-cell rim, one ring out to sea. The rim's
#          ~10 km margin is far beyond the 2.4 km tolerance at zoom 5.
#   z3-4 : resolution-5 cells, two-cell rim (~25 km margin against 10 km),
#          two rings out to sea so the coast edge sits beyond the tolerance.
#   z0-2 : resolution-4 parents, no rim at all -- fully cumulative, which
#          costs overdraw only where land is a few hundred pixels wide --
#          four rings out to sea against a 39 km tolerance at zoom 1.
#
# The sea margin bleeds across a strait onto the far shore by up to its own
# width, which at these zooms is one to three pixels; the water layer hides
# the rest. tippecanoe runs Visvalingam (emit/tiles.py) so what remains of the
# hex edge at low zoom is rounded away rather than left as spikes.
LODS = (
    {"minzoom": 5, "maxzoom": None, "res": 5, "rim": 1, "rings": 1},
    {"minzoom": 3, "maxzoom": 4, "res": 5, "rim": 2, "rings": 2},
    {"minzoom": 0, "maxzoom": 2, "res": 4, "rim": None, "rings": 4},
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


def _fine_features(lod: dict, cells_arr, nb, ring, band) -> list[dict]:
    """Resolution-5 bands with a rim of `lod['rim']` cells over the faster ones."""
    sub = ring <= lod["rings"]
    # A neighbour outside this level's universe does not exist for it: it
    # neither blocks interiority nor gets painted.
    nb_sub = np.where((nb >= 0) & sub[np.maximum(nb, 0)], nb, -1)
    slowest_nb = np.where(nb_sub >= 0, band[np.maximum(nb_sub, 0)], -1).max(axis=1)
    out = []
    for k in np.unique(band[sub]).tolist():
        interior = (band <= k - 1) & (slowest_nb <= k - 1)
        for _ in range(lod["rim"] - 1):
            # Widen the rim: a cell is interior only if every existing
            # neighbour is interior too.
            interior &= np.where(nb_sub >= 0, interior[np.maximum(nb_sub, 0)], True).all(axis=1)
        keep = sub & (band <= k) & ~interior
        geometry = _dissolve(cells_arr[keep].tolist())
        if geometry is not None and not geometry.is_empty:
            out.append(_feature(k, geometry, lod))
    return out


def _coarse_features(lod: dict, cells_arr, ring, band) -> list[dict]:
    """Cumulative bands over coarser parents: a parent is within edge k when
    any of its children is."""
    import h3

    sub = ring <= lod["rings"]
    parents = np.array([h3.cell_to_parent(c, lod["res"]) for c in cells_arr[sub]], dtype=object)
    uniq, inverse = np.unique(parents, return_inverse=True)
    fastest = np.full(len(uniq), np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(fastest, inverse, band[sub])
    out = []
    for k in np.unique(band[sub]).tolist():
        geometry = _dissolve(uniq[fastest <= k].tolist())
        if geometry is not None and not geometry.is_empty:
            out.append(_feature(k, geometry, lod))
    return out


def band_feature_collection(idx, cell_minutes: np.ndarray, grid=None) -> dict:
    """GeoJSON FeatureCollection: one feature per occupied band per level of
    detail (see LODS), each level in ascending band order with unreachable
    land last.

    `grid` is the `contour.grid.universe` of `idx.cells`; the build computes
    it once in the parent process and hands it to every forked worker.
    """
    if len(cell_minutes) < idx.n_cells:
        raise ValueError("cell_minutes shorter than the cell universe")
    from transport_maps.contour import grid as grid_mod

    cells, nb, ring = grid if grid is not None else grid_mod.universe(idx.cells)
    n_land = idx.n_cells
    if len(cells) < n_land or cells[:n_land] != list(idx.cells):
        raise ValueError("render grid does not match the cell universe")

    # Each sea ring takes the fastest cell of the ring inside it. Outer rings
    # are still +inf when an inner one is filled, so the minimum only ever
    # sees the ring inside.
    minutes = np.full(len(cells), np.inf)
    minutes[:n_land] = np.asarray(cell_minutes[:n_land], dtype=float)
    for r in range(1, int(ring.max()) + 1 if len(ring) else 1):
        sel = np.flatnonzero(ring == r)
        nbs = nb[sel]
        minutes[sel] = np.where(nbs >= 0, minutes[np.maximum(nbs, 0)], np.inf).min(axis=1)
    band = band_indices(minutes)
    cells_arr = np.array(cells, dtype=object)

    features: list[dict] = []
    for lod in LODS:
        if lod["res"] == config.SOLVE_RES:
            features += _fine_features(lod, cells_arr, nb, ring, band)
        else:
            features += _coarse_features(lod, cells_arr, ring, band)
    return {"type": "FeatureCollection", "features": features}
