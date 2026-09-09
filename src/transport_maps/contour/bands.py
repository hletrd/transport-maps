"""Per-cell minutes -> dissolved isochrone band polygons."""

import bisect

import h3
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union

from transport_maps import config

UNREACHABLE_BAND = -1
# ~1.1 km; see _land() for why.
# ~110 m. Natural Earth 10m carries 445,356 coastline vertices; the previous
# 0.01 (~1.1 km) threw away 64% of them and was the reason the outline looked
# coarse. At this tolerance 90% survive, and the union actually builds FASTER
# (1.1 s against 5.3 s) because there is less generalising to do.
LAND_SIMPLIFY_DEG = 0.001


def band_of(minutes: float) -> int:
    """Band index for a time. Values above the last edge fall in the open band."""
    if not np.isfinite(minutes):
        return UNREACHABLE_BAND
    return bisect.bisect_left(config.BAND_EDGES_MIN, minutes)


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


_land_cache = None


def _land() -> "shapely.Geometry":
    """Simplified land outline used to clip band edges to real coastlines.

    Without this, every coastline is drawn as H3 hex edges: 9.9 km segments
    against Natural Earth's ~0.1 km detail, which reads as a hexagonal world.
    Simplifying to ~1.1 km keeps the outline 9x finer than the hex grid while
    cutting 422k vertices to 151k. Clipping costs about 0.9 s per origin.
    """
    global _land_cache
    if _land_cache is None:
        from transport_maps.sources import landmask
        merged = shapely.union_all(landmask._land_parts())
        _land_cache = shapely.make_valid(shapely.simplify(merged, LAND_SIMPLIFY_DEG))
    return _land_cache


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
    # Smooth BEFORE clipping, so the coastline stays exact: rounding a band and
    # the shore together would eat headlands and round off every island.
    return _polygonal(shapely.make_valid(shapely.intersection(_smooth(merged), _land())))


def band_feature_collection(idx, cell_minutes: np.ndarray) -> dict:
    """GeoJSON FeatureCollection, one polygon feature per occupied band.

    Dissolution returns a Polygon for contiguous cells and a MultiPolygon when
    a band is split across regions; both serialise correctly. Cells that
    straddle the antimeridian are handled separately by `_dissolve`, since
    h3's own dissolve reads their ring as spanning the globe backwards.
    """
    if len(cell_minutes) < idx.n_cells:
        raise ValueError("cell_minutes shorter than the cell universe")

    by_band: dict[int, list[str]] = {}
    for pos, cell in enumerate(idx.cells):
        band = band_of(float(cell_minutes[pos]))
        by_band.setdefault(band, []).append(cell)

    # Unreachable land is emitted as its own feature rather than dropped.
    # Dropping it left Antarctica -- which no scheduled service reaches -- with
    # no polygon at all, so it rendered as open ocean: the land mask had it,
    # the map did not. It carries UNREACHABLE_BAND so the style can give it a
    # "no route" tone instead of a travel-time colour.
    # Bands share boundaries, and smoothing each one on its own moves those
    # boundaries in different directions, so neighbours overlap. Subtracting
    # everything already emitted makes disjointness structural instead of
    # something the gate has to hope for. Reachable bands go first, ascending,
    # so a nearer band always wins the contested sliver; unreachable land is
    # emitted last and takes only what is left.
    order = sorted(b for b in by_band if b != UNREACHABLE_BAND)
    if UNREACHABLE_BAND in by_band:
        order.append(UNREACHABLE_BAND)

    features = []
    claimed = None
    for band in order:
        geometry = _dissolve(by_band[band])
        if claimed is not None:
            geometry = shapely.make_valid(shapely.difference(geometry, claimed))
        if geometry.is_empty:
            continue
        claimed = (geometry if claimed is None
                   else shapely.make_valid(shapely.union_all([claimed, geometry])))
        features.append({
            "type": "Feature",
            "properties": {
                "band": band,
                # None for the open band AND for unreachable land: band -1
                # would otherwise index BAND_EDGES_MIN from the end and claim
                # the unreachable cells are inside the last edge.
                "max_minutes": (
                    config.BAND_EDGES_MIN[band]
                    if 0 <= band < len(config.BAND_EDGES_MIN)
                    else None
                ),
            },
            "geometry": mapping(geometry),
        })

    return {"type": "FeatureCollection", "features": features}
