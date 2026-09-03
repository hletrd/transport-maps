"""Publication gates. Every check aborts the build rather than shipping bad data."""

import numpy as np
from shapely.geometry import shape

MIN_COVERAGE = 0.90


def check_coverage(minutes: np.ndarray, idx) -> float:
    """Fraction of land cells with any path to the origin."""
    return float(np.isfinite(minutes[: idx.n_cells]).mean())


def check_bands_disjoint(feature_collection: dict) -> None:
    geoms = [shape(f["geometry"]) for f in feature_collection["features"]]
    for i, a in enumerate(geoms):
        for b in geoms[i + 1:]:
            if a.intersection(b).area > 1e-9:
                raise ValueError("isochrone bands overlap; dissolution is broken")


def check_monotonic_ground(idx, minutes: np.ndarray) -> None:
    """Dijkstra's invariant: no cell beats reaching it via an adjacent cell.

    For adjacent p and q, minutes[q] must not exceed minutes[p] plus the ACTUAL
    cost of the p->q ground hop. Charge the real edge weight, which is the hop
    distance divided by the DESTINATION cell's speed -- the same rule
    ground.hex_edges uses.

    An earlier draft compared against the fastest speed on the grid (85 km/h,
    about 10.6 minutes per hop). That is wrong: ground speeds span 5 to 85 km/h,
    so a roadless neighbour legitimately costs about 180 minutes, and the tight
    bound fails on any slow terrain. Do not reintroduce a single global bound.
    """
    import h3

    from transport_maps.graph import ground

    speeds = ground.cell_speed_kmh(idx)
    stride = 997  # sample; a full sweep is O(n * 7) and this gate runs per origin
    for pos in range(0, idx.n_cells, stride):
        here = float(minutes[pos])
        if not np.isfinite(here):
            continue
        cell = idx.cells[pos]
        origin_latlng = np.array([h3.cell_to_latlng(cell)])
        for neighbour in h3.grid_disk(cell, 1):
            if neighbour == cell:
                continue
            q = idx.try_cell_index(neighbour)
            if q is None or not np.isfinite(minutes[q]):
                continue
            distance = ground.haversine_km(
                origin_latlng, np.array([h3.cell_to_latlng(neighbour)])
            )[0]
            hop = distance / speeds[q] * 60.0
            if minutes[q] > here + hop + 1e-6:
                raise ValueError(
                    f"cell {neighbour} is {minutes[q]:.1f} min but its neighbour "
                    f"{cell} is {here:.1f} min and the hop costs only {hop:.1f} min; "
                    "the solver or the ground edges are inconsistent"
                )
