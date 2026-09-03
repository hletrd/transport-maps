"""Hex-to-hex ground edges."""

import h3
import numpy as np

from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import roads

# Index by GRIP road class: 0 = roadless, 1 = highway .. 5 = local road.
SPEED_BY_ROAD_CLASS_KMH = np.array([5.0, 85.0, 60.0, 40.0, 30.0, 25.0], dtype=np.float64)


def cell_speed_kmh(idx: NodeIndex) -> np.ndarray:
    """Effective ground speed per cell, indexed by cell position."""
    centroids = np.array([h3.cell_to_latlng(c) for c in idx.cells], dtype=np.float64)
    classes = roads.sample_class(centroids[:, 0], centroids[:, 1])
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
