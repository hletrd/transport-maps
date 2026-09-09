"""Hex-to-hex ground edges."""

import logging

import h3
import numpy as np

from transport_maps.graph import transfers
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import countries, roads, urban

logger = logging.getLogger(__name__)

# Index by GRIP road class: 0 = roadless, 1 = highway .. 5 = local road.
#
# FITTED against 1,383 real driving journeys sampled from Google Routes between
# populated places (scripts/calibrate_ground.py). Classes 1-4 are fitted;
# roadless and local keep their published-figure defaults because the sample
# could not speak to them -- roadless drew 103 km across 6 journeys and local
# none at all, and an unguarded fit returned 58 km/h for ROADLESS terrain,
# which is not merely wrong but impossible.
SPEED_BY_ROAD_CLASS_KMH = np.array([5.0, 107.0, 49.0, 36.0, 25.0, 25.0], dtype=np.float64)


def _land_border_min() -> float:
    import tomllib

    from transport_maps import config

    with open(config.ROOT / "calibration.toml", "rb") as fh:
        return float(tomllib.load(fh)["land_border"]["crossing_min"])


def cell_speed_kmh(idx: NodeIndex) -> np.ndarray:
    """Effective ground speed per cell, indexed by cell position."""
    # Footprint aggregation, NOT centroid sampling: an H3 res-5 cell spans 3-6
    # GRIP4 cells, and sampling the centre alone reports 51.5% of land roadless
    # against a true 29.3%, depressing mean ground speed from 36.8 to 23.9 km/h.
    classes = roads.cell_class(idx.cells)
    speeds = SPEED_BY_ROAD_CLASS_KMH[classes]
    # GRIP4 gives a cell the grade of its BEST road, so a dense city cell with a
    # motorway through it is charged at motorway speed. Measured over 112 real
    # city-to-airport journeys that made urban access 2.03x too fast, against
    # only 1.12x between towns: the error is in built-up areas, not on the open
    # road. Dividing marked cells by the fitted factor brings urban access to
    # 1.02x and inter-town to 1.06x.
    # Only where there are roads to be congested. A roadless cell is already at
    # walking pace, and traffic does not make walking slower -- halving it to
    # 2.5 km/h would put the slowest terrain on Earth below its own floor.
    congested = urban.urban_mask(idx.cells) & (classes > 0)
    speeds = np.where(congested, speeds / urban.URBAN_CONGESTION_FACTOR, speeds)
    return speeds


def hex_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Directed edges between adjacent land cells, weighted in minutes.

    Traversing from u into v is charged at v's speed, so slow terrain costs you
    on entry regardless of which side you approach from.
    """
    speeds = cell_speed_kmh(idx)
    centroids = np.array([h3.cell_to_latlng(c) for c in idx.cells], dtype=np.float64)

    # Adjacency alone asserts that every border on Earth can be walked across.
    # Some cannot, and a road route through the inter-Korean border made Seoul
    # reachable overland from Vladivostok.
    country = countries.cell_country(idx.cells)
    zone = np.array([transfers.immigration_zone(countries.iso2(c)) if c else ""
                     for c in country])
    crossing_min = _land_border_min()

    rows: list[int] = []
    cols: list[int] = []
    # Extra minutes per edge, over and above the distance cost: a passport
    # desk on every ground edge that leaves an immigration zone. Without this
    # Singapore to Johor Bahru was a fifteen-minute drive.
    extra: list[float] = []
    blocked = 0
    crossings = 0
    for u, cell in enumerate(idx.cells):
        for neighbour in h3.grid_disk(cell, 1):
            if neighbour == cell:  # grid_disk includes the centre cell
                continue
            v = idx.try_cell_index(neighbour)
            if v is None:
                continue
            if countries.is_closed(country[u], country[v]):
                blocked += 1
                continue
            rows.append(u)
            cols.append(v)
            if zone[u] and zone[v] and zone[u] != zone[v]:
                extra.append(crossing_min)
                crossings += 1
            else:
                extra.append(0.0)
    if blocked:
        logger.info("%d ground edge(s) cut at closed land borders", blocked)
    if crossings:
        logger.info("%d ground edge(s) charged %.0f min for a border crossing",
                    crossings, crossing_min)

    r = np.asarray(rows, dtype=np.int64)
    c = np.asarray(cols, dtype=np.int64)
    dist_km = haversine_km(centroids[r], centroids[c])
    minutes = dist_km / speeds[c] * 60.0 + np.asarray(extra, dtype=np.float64)
    return r, c, minutes


def haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Great-circle distance between arrays of (lat, lon). Public: rail and ferry use it."""
    lat1, lon1 = np.radians(a[:, 0]), np.radians(a[:, 1])
    lat2, lon2 = np.radians(b[:, 0]), np.radians(b[:, 1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(h))
