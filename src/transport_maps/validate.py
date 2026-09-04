"""Publication gates. Every check aborts the build rather than shipping bad data."""

import numpy as np
from scipy.sparse.csgraph import connected_components
from shapely.geometry import shape

MIN_COVERAGE = 0.90

# A scheduled-service airport in a component cut off from the rest of the graph
# is unreachable from every origin, whatever the coverage number says. A few
# are genuine and permanent: 9 of 3,983 today (0.23%) -- AGJ, AJN, CYO, CYU,
# FHZ, FUT, IBB, XYA, YAS -- small-island fields whose Wikipedia pages yield no
# resolvable destination, so they sit alone with their island's land cells.
# Hundreds would mean the route network or the land mask broke.
MAX_ISOLATED_AIRPORT_FRACTION = 0.01


def check_coverage(minutes: np.ndarray, idx) -> float:
    """Fraction of land cells with any path to the origin."""
    return float(np.isfinite(minutes[: idx.n_cells]).mean())


def check_bands_disjoint(feature_collection: dict) -> None:
    geoms = [shape(f["geometry"]) for f in feature_collection["features"]]
    for i, a in enumerate(geoms):
        for b in geoms[i + 1:]:
            if a.intersection(b).area > 1e-9:
                raise ValueError("isochrone bands overlap; dissolution is broken")


def check_monotonic_ground(idx, minutes: np.ndarray, speeds: np.ndarray) -> None:
    """Dijkstra's invariant: no cell beats reaching it via an adjacent cell.

    For adjacent p and q, minutes[q] must not exceed minutes[p] plus the ACTUAL
    cost of the p->q ground hop. Charge the real edge weight, which is the hop
    distance divided by the DESTINATION cell's speed -- the same rule
    ground.hex_edges uses.

    An earlier draft compared against the fastest speed on the grid (85 km/h,
    about 10.6 minutes per hop). That is wrong: ground speeds span 5 to 85 km/h,
    so a roadless neighbour legitimately costs about 180 minutes, and the tight
    bound fails on any slow terrain. Do not reintroduce a single global bound.

    `speeds` is `ground.cell_speed_kmh(idx)`, computed once by the caller. This
    gate runs once per origin (157 times in a full build), and the grid it is
    derived from does not change between origins; recomputing it here cost
    ~4.8s of `roads.cell_class` work per origin for a value the caller already
    has.
    """
    import h3

    from transport_maps.graph import ground

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


def check_airport_connectivity(idx, csr, isolated_out: list[str] | None = None) -> None:
    """No scheduled-service airport may sit in a disconnected component.

    Coverage cannot stand in for this. It is measured per origin over land
    CELLS, so an airport orphaned from the network costs at most the handful of
    cells on its own island -- far too little to move a 90% threshold, while
    every route through it silently disappears.

    Weak connectivity is the right notion here: the graph is directed only
    because ground hops and access/egress are charged asymmetrically, so a node
    reachable in either direction is genuinely wired in.
    """
    _, labels = connected_components(csr, directed=True, connection="weak")
    main = int(np.argmax(np.bincount(labels)))
    isolated = [
        iata for i, iata in enumerate(idx.airports) if labels[idx.n_cells + i] != main
    ]
    if isolated_out is not None:
        isolated_out.extend(isolated)

    limit = MAX_ISOLATED_AIRPORT_FRACTION * len(idx.airports)
    if len(isolated) > limit:
        raise ValueError(
            f"{len(isolated)} of {len(idx.airports)} scheduled-service airports are in "
            f"a component disconnected from the graph, above the "
            f"{MAX_ISOLATED_AIRPORT_FRACTION:.0%} bound ({limit:.0f}): "
            f"{', '.join(isolated[:10])}{', ...' if len(isolated) > 10 else ''}"
        )
