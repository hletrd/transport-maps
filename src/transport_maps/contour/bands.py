"""Per-cell minutes -> dissolved isochrone band polygons."""

import bisect

import h3
import numpy as np

from transport_maps import config

UNREACHABLE_BAND = -1


def band_of(minutes: float) -> int:
    """Band index for a time. Values above the last edge fall in the open band."""
    if not np.isfinite(minutes):
        return UNREACHABLE_BAND
    return bisect.bisect_left(config.BAND_EDGES_MIN, minutes)


def band_feature_collection(idx, cell_minutes: np.ndarray) -> dict:
    """GeoJSON FeatureCollection, one polygon feature per occupied band.

    h3.cells_to_h3shape returns a Polygon for contiguous cells and a MultiPolygon
    when a band is split across regions; both serialise correctly.
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
        shape = h3.cells_to_h3shape(by_band[band], tight=True)
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
            "geometry": h3.h3shape_to_geo(shape),
        })

    return {"type": "FeatureCollection", "features": features}
