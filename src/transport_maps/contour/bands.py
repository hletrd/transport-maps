"""Per-cell minutes -> dissolved isochrone band polygons."""

import bisect

import h3
import numpy as np
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

    return unary_union(geoms) if geoms else None


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
        if band == UNREACHABLE_BAND:
            continue
        by_band.setdefault(band, []).append(cell)

    features = []
    for band in sorted(by_band):
        geometry = _dissolve(by_band[band])
        features.append({
            "type": "Feature",
            "properties": {
                "band": band,
                "max_minutes": (
                    config.BAND_EDGES_MIN[band]
                    if band < len(config.BAND_EDGES_MIN)
                    else None
                ),
            },
            "geometry": mapping(geometry),
        })

    return {"type": "FeatureCollection", "features": features}
