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
# are genuine and permanent -- AGJ, AJN, CYO, CYU, FHZ, FUT, IBB, XYA, YAS --
# small-island fields whose Wikipedia pages yield no resolvable destination, so
# they sit alone with their island's land cells. Hundreds would mean the route
# network or the land mask broke.
#
# The count that used to stand here, "9 of 3,983 at res 5 (0.23%, 2026-09)",
# was measured before `config.SOLVE_RES` moved to 6 and has not been re-taken
# since: the solver has not run at res 5 in this repository's recent history,
# so the figure described a grid the build no longer uses. Three sibling files
# carried the same class of stale measurement and were corrected in an earlier
# cycle (`sources/countries.py`, `sources/roads.py`, `emit/tiles.py`); this one
# was missed. The named airports are still the ones the allowlist covers; the
# fraction is left unquantified rather than restated at a resolution nobody
# measured, and the next full build can fill it in from the gate's own log.
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
                      samples: int = COVER_SAMPLE_CELLS, seed: int = 0,
                      skip_native: bool = False) -> None:
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
            # A variant built without this level (bands.band_feature_collection
            # skip_native) has nothing here to check -- and must not be judged
            # as though its missing level were a hole.
            if skip_native:
                continue
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


# Cells the monotonic gate samples per origin: every MONOTONIC_STRIDE-th. A
# full sweep is O(n * 7) and the gate runs once per origin.
MONOTONIC_STRIDE = 997


def _ground_neighbours(idx, pos: int, cell: str, fine: np.ndarray,
                       refined: bool) -> list[int]:
    """Graph positions graph/ground.hex_edges joins `cell` to, before any cut.

    Same-resolution ring neighbours, plus the pairs hex_edges adds across a
    split seam: a fine cell and the unsplit base cell one of its ring
    neighbours falls in. hex_edges adds that pair from the FINE side only (in
    both directions), so from the base side it is found here by looking into
    each absent neighbour's children -- the ones `refine.ground_adjacent`
    says touch this cell, which is the test hex_edges' rule reduces to.
    """
    import h3

    from transport_maps import config
    from transport_maps.graph import refine

    out: list[int] = []
    for neighbour in h3.grid_ring(cell, 1):
        q = idx.try_cell_index(neighbour)
        if q is not None:
            out.append(q)
        elif fine[pos]:
            q = idx.try_cell_index(h3.cell_to_parent(neighbour, config.SOLVE_RES))
            if q is not None and q not in out:
                out.append(q)
        elif refined:
            for child in h3.cell_to_children(neighbour, config.FINE_RES):
                q = idx.try_cell_index(child)
                if (q is not None and fine[q] and q not in out
                        and refine.ground_adjacent(child, cell)):
                    out.append(q)
    return out


def check_monotonic_ground(idx, minutes: np.ndarray, speeds: np.ndarray,
                           country=None, zone=None, stride: int = MONOTONIC_STRIDE) -> None:
    """Dijkstra's invariant: no cell beats reaching it via an adjacent cell.

    For adjacent p and q, minutes[q] must not exceed minutes[p] plus the ACTUAL
    cost of the p->q ground hop. Charge the real edge weight, which is the hop
    distance divided by the DESTINATION cell's speed -- the same rule
    ground.hex_edges uses.

    "Adjacent" is what hex_edges joins, on the mixed grid too: a res-7 cell
    and the unsplit res-6 cell beyond its ring are adjacent in both
    directions, and so are the two ends of a road bridge or tunnel that spans
    a water cell (`idx.spans`, graph/build._span_edges), which are not grid
    neighbours at all. The gate used to look only at same-resolution
    neighbours and so never saw a single seam edge (A14). The mixed-grid tests
    in tests/test_validate.py were run against the old loop -- cross edges
    removed from each direction in turn, spans skipped, the severed check
    dropped from the seam -- and each went red.

    An earlier draft compared against the fastest speed on the grid (85 km/h
    in the superseded spec; the built table tops out at 104 km/h). That is
    wrong: ground speeds span 5 to 104 km/h, so a roadless neighbour
    legitimately costs many times what the fastest one does, and the tight
    bound fails on any slow terrain. Do not reintroduce a single global bound.

    The minutes depend on the resolution, so they are stated per grid rather
    than left as a bare number: centre to centre a res-6 hop is 6.45 km, which
    is 3.7 min at 104 km/h and 77 min at 5 km/h; a res-7 hop is 2.44 km, 1.4
    and 29 min. (The 8.7 and 180 min this note used to give were res-5 figures
    -- 17.07 km per hop -- and survived the move to SOLVE_RES = 6 unchanged;
    T23 corrected the km/h in this very sentence and left the minutes.)

    `speeds` is `ground.cell_speed_kmh(idx)`, computed once by the caller. This
    gate runs once per origin (553 times in a full build), and the grid it is
    derived from does not change between origins; recomputing it here cost
    ~4.8s of `roads.cell_class` work per origin for a value the caller already
    has.
    """
    import h3

    from transport_maps.graph import ground, transfers
    from transport_maps.sources import countries

    # The gate must charge what hex_edges charges. Three things it did not know
    # about: a crossing between immigration zones; a closed border, across
    # which there is no edge at all -- so a neighbour can legitimately be far
    # slower to reach and the invariant simply does not apply; and, the same
    # way, open water between two islands with no bridge or tunnel
    # (graph/landmass, `idx.severed`). The first build to sever them died here
    # on its first origin: Tinian-side cells were rightly far later than their
    # Saipan-side neighbours, with no edge between them to break the invariant.
    # Callers running under fork pass these in; loading them here would call
    # polars and pyogrio from a forked child, which deadlocks.
    if country is None:
        country = countries.cell_country(idx.cells)
    if zone is None:
        zone = [transfers.immigration_zone(countries.iso2(c)) if c else "" for c in country]
    crossing = ground._land_border_min()
    severed = getattr(idx, "severed", frozenset())
    fine_attr = getattr(idx, "fine", np.zeros(0, dtype=bool))
    fine = (fine_attr if len(fine_attr) == idx.n_cells
            else np.zeros(idx.n_cells, dtype=bool))
    refined = bool(fine.any())

    def check(p: int, q: int, hop: float) -> None:
        if zone[p] and zone[q] and zone[p] != zone[q]:
            hop += crossing
        if minutes[q] > minutes[p] + hop + 1e-6:
            raise ValueError(
                f"cell {idx.cells[q]} is {minutes[q]:.1f} min but its neighbour "
                f"{idx.cells[p]} is {minutes[p]:.1f} min and the hop costs only {hop:.1f} min; "
                "the solver or the ground edges are inconsistent"
            )

    for pos in range(0, idx.n_cells, stride):
        if not np.isfinite(minutes[pos]):
            continue
        cell = idx.cells[pos]
        origin_latlng = np.array([h3.cell_to_latlng(cell)])
        for q in _ground_neighbours(idx, pos, cell, fine, refined):
            if not np.isfinite(minutes[q]):
                continue
            if countries.is_closed(country[pos], country[q]):
                continue
            if (pos, q) in severed:
                continue
            distance = ground.haversine_km(
                origin_latlng, np.array([h3.cell_to_latlng(idx.cells[q])])
            )[0]
            check(pos, q, distance / speeds[q] * 60.0)

    # Every span, not a sample: there are a few hundred on Earth and each is
    # the only ground edge across its strait. Charged as _span_edges charges
    # it -- the link's own minutes, plus a zone change, cut at a closed border.
    for (p, q), span_min in (getattr(idx, "spans", None) or {}).items():
        if not (np.isfinite(minutes[p]) and np.isfinite(minutes[q])):
            continue
        if countries.is_closed(country[p], country[q]):
            continue
        check(p, q, float(span_min))


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
