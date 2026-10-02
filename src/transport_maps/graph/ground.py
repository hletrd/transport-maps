"""Hex-to-hex ground edges."""

import logging

import h3
import numpy as np

from transport_maps import config
from transport_maps.graph import refine, transfers
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import countries, roads, urban

logger = logging.getLogger(__name__)


#: calibration.toml [ground] keys in GRIP4 class order, 0 roadless .. 5 local.
GROUND_KEYS = ("roadless_kmh", "highway_kmh", "primary_kmh", "secondary_kmh",
               "tertiary_kmh", "local_kmh")


def load_ground_calibration(path=None) -> tuple[np.ndarray, float]:
    """calibration.toml [ground] and [land_border]: the speed per GRIP4 road
    class and the land-border crossing time, read once.

    The speed table is a mixture -- classes 1-4 FITTED against 2,998 Google
    Routes journeys, roadless (0) and local (5) published-figure defaults --
    and calibration.toml says which is which and why. It lived here as a
    literal until task B2 (2026-10-02), with the same values;
    tests/test_calibration_moved.py pins them.
    """
    import tomllib

    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    table = raw["ground"]
    missing = [k for k in GROUND_KEYS if k not in table]
    if missing:
        raise ValueError(f"{path} [ground] is missing {', '.join(missing)}")
    speeds = np.array([float(table[k]) for k in GROUND_KEYS], dtype=np.float64)
    if not (speeds > 0).all():
        raise ValueError(f"{path} [ground] speeds must be positive; got {speeds.tolist()}")
    return speeds, float(raw["land_border"]["crossing_min"])


# Index by GRIP road class: 0 = roadless, 1 = highway .. 5 = local road.
# Provenance per class is in calibration.toml [ground]. Read ONCE, at import:
# the land-border time used to be re-parsed from the file by every caller,
# including the per-origin monotonicity gate, so an edit to calibration.toml
# during a build could check origins against a constant the graph was not
# weighted with (ARCH-8).
SPEED_BY_ROAD_CLASS_KMH, LAND_BORDER_MIN = load_ground_calibration()

# Directed edge slots preallocated per cell: six ring neighbours plus the
# cross-resolution pairs along split seams. Measured at 8.0 per cell over the
# res-6/7 universe (82 M edges over 10.2 M cells); the guard below turns an
# overflow into a message instead of a bare IndexError hours into a build.
EDGE_SLOTS_PER_CELL = 8


def _land_border_min() -> float:
    """calibration.toml [land_border] crossing_min, as read at import."""
    return LAND_BORDER_MIN


def cell_class(idx: NodeIndex) -> np.ndarray:
    """GRIP4 road class per cell. Computed on the base grid and carried down to
    the fine children: the rasters are 5 arc-minutes, coarser than either grid,
    so a child's class is its parent's, and the per-cell footprint pass over
    ten million cells would buy nothing."""
    if len(getattr(idx, "base_cells", [])):
        return refine.expand(roads.cell_class(idx.base_cells), idx)
    return roads.cell_class(idx.cells)


def urban_mask(idx: NodeIndex) -> np.ndarray:
    if len(getattr(idx, "base_cells", [])):
        return refine.expand(urban.urban_mask(idx.base_cells), idx)
    return urban.urban_mask(idx.cells)


def cell_speed_kmh(idx: NodeIndex, classes: np.ndarray | None = None) -> np.ndarray:
    """Effective ground speed per cell, indexed by cell position.

    `classes` is `cell_class(idx)` when the caller already has it: the build
    does (cli._build_all_locked), and deriving it again is a ~4 M-cell raster
    pass (PR-5).
    """
    # Footprint aggregation, NOT centroid sampling: an H3 cell's window spans 1-4
    # GRIP4 cells, and sampling the centre alone reports 51.5% of land roadless
    # against a true 29.3%, depressing mean ground speed from 36.8 to 23.9 km/h.
    if classes is None:
        classes = cell_class(idx)
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
    congested = urban_mask(idx) & (classes > 0)
    speeds = np.where(congested, speeds / urban.URBAN_CONGESTION_FACTOR, speeds)
    return speeds


def cell_zones(country) -> np.ndarray:
    """Immigration zone per cell from its ISO3 country ("" where none)."""
    return np.array([transfers.immigration_zone(countries.iso2(c)) if c else ""
                     for c in country])


def hex_edges(idx: NodeIndex, speeds: np.ndarray | None = None,
              country: np.ndarray | None = None, zone: np.ndarray | None = None
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Directed edges between adjacent land cells, weighted in minutes.

    Traversing from u into v is charged at v's speed, so slow terrain costs you
    on entry regardless of which side you approach from.

    `speeds`, `country` and `zone` are computed here when not given. The build
    computes them once and passes them down (graph/build.build_graph): each is
    a pass over ~10 M cells, and they were being derived four times over before
    the first origin was solved (PR-5).
    """
    if speeds is None:
        speeds = cell_speed_kmh(idx)
    centroids = np.array([h3.cell_to_latlng(c) for c in idx.cells], dtype=np.float64)

    # Adjacency alone asserts that every border on Earth can be walked across.
    # Some cannot, and a road route through the inter-Korean border made Seoul
    # reachable overland from Vladivostok.
    if country is None:
        country = countries.cell_country(idx.cells)
    if zone is None:
        zone = cell_zones(country)
    crossing_min = _land_border_min()

    # Preallocated: at 82 million edges, three Python lists peaked at 19 GB
    # in the build's parent process, which five forked workers then inherit.
    cap = EDGE_SLOTS_PER_CELL * len(idx.cells)
    rows = np.empty(cap, dtype=np.int32)
    cols = np.empty(cap, dtype=np.int32)
    extra = np.zeros(cap, dtype=np.float64)
    m = 0
    blocked = 0
    severed_edges = 0
    crossings = 0
    fine_attr = getattr(idx, "fine", np.zeros(0, dtype=bool))
    fine = fine_attr if len(fine_attr) == len(idx.cells) else np.zeros(len(idx.cells), dtype=bool)
    # Neighbours with open water between them and no bridge or tunnel
    # (graph/landmass). Empty when the fixed-link extracts are absent.
    severed = getattr(idx, "severed", frozenset())

    def add(u: int, v: int) -> None:
        nonlocal blocked, severed_edges, crossings, m
        if countries.is_closed(country[u], country[v]):
            blocked += 1
            return
        if (u, v) in severed:
            severed_edges += 1
            return
        if m >= cap:
            raise RuntimeError(
                f"ground edge capacity exceeded: more than {EDGE_SLOTS_PER_CELL} edges per "
                f"cell over {len(idx.cells):,} cells; raise EDGE_SLOTS_PER_CELL after "
                "measuring the new split fraction")
        rows[m] = u
        cols[m] = v
        if zone[u] and zone[v] and zone[u] != zone[v]:
            extra[m] = crossing_min
            crossings += 1
        m += 1

    # A fine cell's ring neighbour may lie in an unsplit base cell; then the
    # fine cell and that base cell are adjacent, in both directions. Several
    # of the ring neighbours can share one base parent, so the pair is added
    # once -- coo_matrix SUMS duplicates, which would double the weight.
    cross: set[tuple[int, int]] = set()
    for u, cell in enumerate(idx.cells):
        for neighbour in h3.grid_ring(cell, 1):
            v = idx.try_cell_index(neighbour)
            if v is not None:
                add(u, v)
            elif fine[u]:
                v = idx.try_cell_index(h3.cell_to_parent(neighbour, config.SOLVE_RES))
                if v is not None and (u, v) not in cross:
                    cross.add((u, v))
                    add(u, v)
                    add(v, u)
    rows, cols, extra = rows[:m], cols[:m], extra[:m]
    if blocked:
        logger.info("%d ground edge(s) cut at closed land borders", blocked)
    if severed_edges:
        logger.info("%d ground edge(s) cut across open water with no bridge or tunnel",
                    severed_edges)
    if crossings:
        logger.info("%d ground edge(s) charged %.0f min for a border crossing",
                    crossings, crossing_min)

    r = rows.astype(np.int64)
    c = cols.astype(np.int64)
    dist_km = haversine_km(centroids[r], centroids[c])
    minutes = dist_km / speeds[c] * 60.0 + extra
    return r, c, minutes


def haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Great-circle distance between arrays of (lat, lon).

    Public: `graph/build._ferry_edges` calls it. It used to say "rail and ferry
    use it", and rail does not -- `graph/rail.py` has no import of this module
    at all and carries its own `_haversine_km` with a different signature and
    the same formula. Anyone who trusted the old sentence and changed the
    distance maths here would have missed rail entirely.
    """
    lat1, lon1 = np.radians(a[:, 0]), np.radians(a[:, 1])
    lat2, lon2 = np.radians(b[:, 0]), np.radians(b[:, 1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(h))
