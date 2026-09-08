"""Hex-to-hex ground edges."""

import h3
import numpy as np

from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import roads

# Index by GRIP road class: 0 = roadless, 1 = highway .. 5 = local road.
#
# KNOWN ERROR, measured not guessed: against six real city-to-airport journeys
# this model is about 2.1x too fast (1.4x Tokyo to 4.4x Paris) -- run
# scripts/ground_check.py to reproduce. Two causes, both structural:
#
#   1. These are FREE-FLOW speeds. A dense urban cell contains a motorway, so
#      it is classified 1 and charged 85 km/h -- the motorway's speed, not a
#      city's door-to-door average through signals and congestion.
#   2. hex_edges measures straight lines between cell centroids. Real road
#      distance runs about 1.2-1.3x that, the same circuity the rail model
#      corrects for explicitly.
#
# The table is deliberately NOT tuned to those six journeys: six hand-picked
# routes are far too thin to fit six speeds against, and doing so would trade a
# visible error for a hidden one. Task 13 fits this properly against sampled
# Google Routes journeys, which is what GOOGLE_ROUTES_API_KEY is for.
SPEED_BY_ROAD_CLASS_KMH = np.array([5.0, 85.0, 60.0, 40.0, 30.0, 25.0], dtype=np.float64)


def cell_speed_kmh(idx: NodeIndex) -> np.ndarray:
    """Effective ground speed per cell, indexed by cell position."""
    # Footprint aggregation, NOT centroid sampling: an H3 res-5 cell spans 3-6
    # GRIP4 cells, and sampling the centre alone reports 51.5% of land roadless
    # against a true 29.3%, depressing mean ground speed from 36.8 to 23.9 km/h.
    classes = roads.cell_class(idx.cells)
    return SPEED_BY_ROAD_CLASS_KMH[classes]


def hex_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Directed edges between adjacent land cells, weighted in minutes.

    Traversing from u into v is charged at v's speed, so slow terrain costs you
    on entry regardless of which side you approach from.
    """
    speeds = cell_speed_kmh(idx)
    centroids = np.array([h3.cell_to_latlng(c) for c in idx.cells], dtype=np.float64)

    rows: list[int] = []
    cols: list[int] = []
    for u, cell in enumerate(idx.cells):
        for neighbour in h3.grid_disk(cell, 1):
            if neighbour == cell:  # grid_disk includes the centre cell
                continue
            v = idx.try_cell_index(neighbour)
            if v is not None:
                rows.append(u)
                cols.append(v)

    r = np.asarray(rows, dtype=np.int64)
    c = np.asarray(cols, dtype=np.int64)
    dist_km = haversine_km(centroids[r], centroids[c])
    minutes = dist_km / speeds[c] * 60.0
    return r, c, minutes


def haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Great-circle distance between arrays of (lat, lon). Public: rail and ferry use it."""
    lat1, lon1 = np.radians(a[:, 0]), np.radians(a[:, 1])
    lat2, lon2 = np.radians(b[:, 0]), np.radians(b[:, 1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(h))
