"""Publication gates. Every check aborts the build rather than shipping bad data."""

import numpy as np
from scipy.sparse.csgraph import connected_components
from shapely.geometry import shape

MIN_COVERAGE = 0.90
# Antarctica: charted, but with no scheduled service it can never be reached.
# See check_coverage.
KNOWN_UNREACHABLE_MAX_LAT = -60.0

# A scheduled-service airport in a component cut off from the rest of the graph
# is unreachable from every origin, whatever the coverage number says. A few
# are genuine and permanent: 9 of 3,983 today (0.23%) -- AGJ, AJN, CYO, CYU,
# FHZ, FUT, IBB, XYA, YAS -- small-island fields whose Wikipedia pages yield no
# resolvable destination, so they sit alone with their island's land cells.
# Hundreds would mean the route network or the land mask broke.
MAX_ISOLATED_AIRPORT_FRACTION = 0.01


def check_coverage(minutes: np.ndarray, idx) -> float:
    """Fraction of REACHABLE-IN-PRINCIPLE land cells that a route actually reaches.

    Antarctica is excluded from the denominator. It is charted so the globe has
    no hole in it, but it has no scheduled passenger service, so every one of
    its ~43,500 cells is unreachable by construction. Counting them would drag
    a perfect build down to about 92% and leave only two points of headroom
    above MIN_COVERAGE -- turning a gate that should catch real regressions into
    one that mostly measures how much of Antarctica we drew.
    """
    import h3

    reachable_in_principle = np.fromiter(
        (h3.cell_to_latlng(c)[0] > KNOWN_UNREACHABLE_MAX_LAT for c in idx.cells),
        dtype=bool,
        count=idx.n_cells,
    )
    considered = minutes[: idx.n_cells][reachable_in_principle]
    # A universe with no reachable-in-principle cell at all cannot be measured.
    # The mean of nothing is NaN, and `NaN < MIN_COVERAGE` is False, so the
    # gate in cli._solve_one would wave such an origin through; zero fails it.
    if considered.size == 0:
        return 0.0
    return float(np.isfinite(considered).mean())


# Hex vertices sampled per origin and level. Gaps, when the construction is
# wrong, are systematic -- at every band junction -- so a sample this size
# cannot miss them, and the full 3.6 million vertices would cost minutes.
COVER_SAMPLE_CELLS = 20_000


def check_bands_cover(idx, grid, native, feature_collection: dict,
                      samples: int = COVER_SAMPLE_CELLS, seed: int = 0) -> None:
    """Every interior hex vertex must lie inside at least one emitted band,
    at every level of detail.

    Bands overlap by whole cells (contour.bands) so that no gap can open
    between neighbours; this checks that promise on the emitted geometry, at
    the hex VERTICES, where holes used to appear. Interior cells only: each
    level's outer edge is legitimately open sea.
    """
    import shapely

    from transport_maps.contour import bands

    cells6, nb6, ring6 = grid
    _rows, _cols, complete = native
    for i, lod in enumerate(bands.LODS):
        if lod["kind"] == "native":
            cells = list(idx.cells)
            interior = np.flatnonzero(complete)
        else:
            # Strictly inside this level's base universe. The coarse level is
            # built from parents, whose edges wander from the children's, so
            # it is judged further in.
            depth = lod["rings"] - (1 if lod["kind"] == "base" else 3)
            if lod["kind"] == "coarse":
                depth = 1
            inside = (ring6 <= depth) & (nb6 >= 0).all(axis=1) \
                     & (ring6[np.maximum(nb6, 0)] <= lod.get("rings", 0)).all(axis=1)
            cells = cells6
            interior = np.flatnonzero(inside)
        if len(interior) == 0:
            continue
        rng = np.random.default_rng(seed)
        pick = rng.choice(interior, size=min(samples, len(interior)), replace=False)
        # Each vertex pulled 3% of the way to its cell's centre. A vertex that
        # sits exactly on a shared edge is inside neither polygon by strict
        # containment even when the two meet perfectly -- on the mixed grid a
        # fine cell's corner lies on the seam between its parent and the next
        # base cell -- while the holes this gate exists for are cells wide.
        pts = np.array([pt for c in pick for pt in _pulled_in_vertices(cells[c])])

        # Features are multipolygons whose parts may overlap (contour.bands),
        # which GEOS predicates do not accept on the whole; the parts are
        # indexed and tested one by one.
        parts = [g for f in bands.lod_features(feature_collection, i)
                 for g in shapely.get_parts(shape(f["geometry"]))]
        covered = np.zeros(len(pts), dtype=bool)
        if parts:
            tree = shapely.STRtree(parts)
            hit_pts, _ = tree.query(shapely.points(pts), predicate="within")
            covered[np.unique(hit_pts)] = True
        if not covered.all():
            n = int((~covered).sum())
            raise ValueError(
                f"level {i} (zoom {lod['minzoom']}+): {n:,} of {len(pts):,} interior hex "
                "vertices fall between bands")


def _pulled_in_vertices(cell: str) -> list[tuple[float, float]]:
    """Each vertex of `cell` pulled 3 % toward its centre, as (lon, lat).

    The interpolation runs in an unwrapped frame: for a cell straddling the
    antimeridian a vertex at +179.96 and a centre at -179.95 differ by 0.09
    degrees of longitude, not 359.9, and the planar formula put the sample
    point eleven degrees away in another band (or the open sea) -- a gate
    failure on correct geometry, latent only because the seed-0 sample never
    happened to pick such a cell.
    """
    import h3

    clat, clon = h3.cell_to_latlng(cell)
    out = []
    for lat, lon in h3.cell_to_boundary(cell):
        dlon = lon - clon
        if dlon > 180.0:
            dlon -= 360.0
        elif dlon < -180.0:
            dlon += 360.0
        plon = clon + 0.97 * dlon
        if plon > 180.0:
            plon -= 360.0
        elif plon < -180.0:
            plon += 360.0
        out.append((plon, clat + 0.97 * (lat - clat)))
    return out


def check_monotonic_ground(idx, minutes: np.ndarray, speeds: np.ndarray,
                           country=None, zone=None) -> None:
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

    from transport_maps.graph import ground, transfers
    from transport_maps.sources import countries

    # The gate must charge what hex_edges charges. Two things it did not know
    # about: a crossing between immigration zones, and a closed border, across
    # which there is no edge at all -- so a neighbour can legitimately be far
    # slower to reach and the invariant simply does not apply.
    # Callers running under fork pass these in; loading them here would call
    # polars and pyogrio from a forked child, which deadlocks.
    if country is None:
        country = countries.cell_country(idx.cells)
    if zone is None:
        zone = [transfers.immigration_zone(countries.iso2(c)) if c else "" for c in country]
    crossing = ground._land_border_min()

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
            if countries.is_closed(country[pos], country[q]):
                continue
            distance = ground.haversine_km(
                origin_latlng, np.array([h3.cell_to_latlng(neighbour)])
            )[0]
            hop = distance / speeds[q] * 60.0
            if zone[pos] and zone[q] and zone[pos] != zone[q]:
                hop += crossing
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
