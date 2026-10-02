from typing import ClassVar

import h3
import numpy as np
import pytest
import scipy.sparse as sp

from transport_maps import config, validate
from transport_maps.graph import ground


def test_coverage_is_the_reachable_fraction():
    minutes = np.array([10.0, 20.0, np.inf, np.inf])

    class Idx:
        n_cells = 4
        # Non-Antarctic cells, so none are allowlisted out.
        cells: ClassVar[list[str]] = [h3.latlng_to_cell(10.0 + i, 0.0, 5) for i in range(4)]
    assert validate.check_coverage(minutes, Idx()) == 0.5


def test_the_mask_built_once_gives_the_coverage_derived_per_origin():
    """R3: the build computes `reachable_in_principle` once and hands it to
    every origin. Two temperate cells and two Antarctic ones, one of each
    reached: the mask is the hand-written one and the coverage is the same
    whether the mask is passed or derived. Mutation performed and reverted:
    the mask's `>` turned to `<` -> red."""
    class Idx:
        n_cells = 4
        cells: ClassVar[list[str]] = [h3.latlng_to_cell(lat, 0.0, 5)
                                      for lat in (10.0, 20.0, -75.0, -89.0)]
    minutes = np.array([1.0, np.inf, np.inf, 5.0])
    mask = validate.reachable_in_principle(Idx())
    assert mask.tolist() == [True, True, False, False]
    assert validate.check_coverage(minutes, Idx(), mask) == validate.check_coverage(minutes, Idx()) == 0.5


def test_low_coverage_trips_the_publish_threshold():
    """build-all compares check_coverage's return against MIN_COVERAGE before
    shipping (see cli._build_all). A gate that always reports full coverage
    would let a broken solve through, so pin that a mostly-unreachable input
    actually lands below the threshold.
    """
    minutes = np.concatenate([np.full(5, 1.0), np.full(95, np.inf)])

    class Idx:
        n_cells = 100
        # Non-Antarctic cells, so none are allowlisted out.
        cells: ClassVar[list[str]] = [h3.latlng_to_cell(10.0 + i, 0.0, 5) for i in range(100)]
    assert validate.check_coverage(minutes, Idx()) < validate.MIN_COVERAGE


def _hex_universe():
    """A 19-cell disk with its sea rings, the shape the gate expects."""
    from transport_maps.contour import grid
    centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    cells = sorted(h3.grid_disk(centre, 2))

    class Idx:
        pass
    idx = Idx(); idx.cells = cells; idx.n_cells = len(cells)
    return idx, grid.universe(cells), grid.native_edges(idx)


def _features(geom, band=0):
    """The same geometry at every level of detail."""
    from shapely.geometry import mapping

    from transport_maps.contour import bands
    out = []
    for lod in bands.LODS:
        z = {"minzoom": lod["minzoom"]}
        if lod["maxzoom"] is not None:
            z["maxzoom"] = lod["maxzoom"]
        out.append({"tippecanoe": z, "properties": {"band": band}, "geometry": mapping(geom)})
    return out


def _whole(cells):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    return unary_union([Polygon([(lo, la) for la, lo in h3.cell_to_boundary(c)]) for c in cells])


def test_a_hole_between_bands_is_rejected():
    """The gate must see a gap at an interior hex vertex, not just at centroids."""
    from shapely.geometry import Point
    idx, grid, native = _hex_universe()
    cells6 = grid[0]
    # Punch out a disc around one vertex of the CENTRE land cell.
    la, lo = h3.cell_to_boundary(idx.cells[len(idx.cells) // 2])[0]
    holed = _whole(cells6).difference(Point(lo, la).buffer(0.004))   # ~440 m, past the 3% pull-in
    with pytest.raises(ValueError, match="between bands"):
        validate.check_bands_cover(idx, grid, native, {"features": _features(holed)}, samples=len(cells6))


def test_a_level_with_no_features_is_rejected():
    """A missing level would leave those zooms blank without any error."""
    idx, grid, native = _hex_universe()
    only_native = _features(_whole(grid[0]).buffer(1e-6))[:1]
    with pytest.raises(ValueError, match="level 1"):
        validate.check_bands_cover(idx, grid, native, {"features": only_native}, samples=len(grid[0]))


def test_full_coverage_is_accepted():
    idx, grid, native = _hex_universe()
    validate.check_bands_cover(idx, grid, native, {"features": _features(_whole(grid[0]).buffer(1e-6))},
                               samples=len(grid[0]))  # must not raise


class _TwoCellIdx:
    """Minimal idx double: two genuinely-adjacent H3 cells, nothing else."""

    def __init__(self, cell: str, neighbour: str):
        self.n_cells = 2
        self.cells = [cell, neighbour]
        self._pos = {cell: 0, neighbour: 1}

    def try_cell_index(self, cell: str) -> int | None:
        return self._pos.get(cell)


def _adjacent_pair() -> tuple[str, str]:
    seoul = h3.latlng_to_cell(37.5665, 126.9780, config.SOLVE_RES)
    neighbour = next(c for c in h3.grid_disk(seoul, 1) if c != seoul)
    return seoul, neighbour


# Both cells of the pair lie in South Korea. The gate takes country and zone
# from its caller (the build computes them once, in the parent: S2).
_ONE_COUNTRY = {"country": np.array(["KOR", "KOR"]), "zone": ["", ""]}


def test_inconsistent_neighbour_time_is_rejected():
    """A neighbour reported far more expensive than the actual hop from an
    already-reached cell violates Dijkstra's own invariant.
    """
    cell, neighbour = _adjacent_pair()
    idx = _TwoCellIdx(cell, neighbour)
    # The real one-hop cost between adjacent res-5 cells is at most a few
    # hundred minutes even over roadless terrain (5 km/h floor); 1e6 minutes
    # is unreachable via any legitimate hop cost.
    minutes = np.array([0.0, 1e6])

    with pytest.raises(ValueError, match="inconsistent"):
        validate.check_monotonic_ground(idx, minutes, ground.cell_speed_kmh(idx),
                                        **_ONE_COUNTRY)


def test_consistent_neighbour_time_is_accepted():
    """Sanity companion to the rejection test: a neighbour time within the
    real hop cost of its already-reached neighbour must not raise.
    """
    cell, neighbour = _adjacent_pair()
    idx = _TwoCellIdx(cell, neighbour)
    minutes = np.array([0.0, 0.0])  # reaching the neighbour "for free" only helps

    # must not raise
    validate.check_monotonic_ground(idx, minutes, ground.cell_speed_kmh(idx),
                                    **_ONE_COUNTRY)


def test_a_severed_pair_is_exempt_like_a_closed_border():
    """Open water with no bridge between two islands means no ground edge, so
    the far island can rightly be much later than its neighbour across it.

    The first build to sever Saipan from Tinian died on its first origin here:
    the gate still assumed every pair of grid neighbours was joined. Same cells
    and same times as `test_inconsistent_neighbour_time_is_rejected`, which is
    the control -- that one must raise and this one must not.
    """
    cell, neighbour = _adjacent_pair()
    idx = _TwoCellIdx(cell, neighbour)
    idx.severed = frozenset({(0, 1), (1, 0)})
    minutes = np.array([0.0, 1e6])

    # must not raise
    validate.check_monotonic_ground(idx, minutes, ground.cell_speed_kmh(idx),
                                    **_ONE_COUNTRY)


def test_the_border_minute_handed_in_is_the_one_charged():
    """R3: the build reads the land-border minute once and passes it as
    `crossing_min`. Across a zone change at 50 km/h, a neighbour 30 minutes
    later than the hop is within the calibrated crossing whether the minute
    is passed or read here, and outside it when the caller says 0. Mutation
    performed and reverted: `crossing_min` ignored -> red."""
    cell, neighbour = _adjacent_pair()
    idx = _TwoCellIdx(cell, neighbour)
    hop = float(ground.haversine_km(np.array([h3.cell_to_latlng(cell)]),
                                    np.array([h3.cell_to_latlng(neighbour)]))[0]) / 50.0 * 60.0
    minutes = np.array([0.0, hop + 30.0])
    zones = {"country": np.array(["KOR", "KOR"]), "zone": ["a", "b"]}
    speeds = np.full(2, 50.0)
    assert ground._land_border_min() > 30.0, "fixture: the crossing must exceed 30 min"
    validate.check_monotonic_ground(idx, minutes, speeds, stride=1, **zones)
    validate.check_monotonic_ground(idx, minutes, speeds, stride=1,
                                    crossing_min=ground._land_border_min(), **zones)
    with pytest.raises(ValueError, match="inconsistent"):
        validate.check_monotonic_ground(idx, minutes, speeds, stride=1, crossing_min=0.0, **zones)


# --- Graph connectivity gate (I3) --------------------------------------------
#
# The spec calls for a gate on "a disconnected component containing a
# scheduled-service airport". It was never implemented, and coverage cannot
# stand in for it: an orphaned airport costs only the handful of land cells on
# its own island, far too few to move a 90% threshold, while every route
# through it silently vanishes.


class _TinyGraphIdx:
    """`n_cells` land cells then two airports, wired by the caller's matrix."""

    def __init__(self, n_cells: int = 2):
        self.n_cells = n_cells
        # Real H3 ids, not placeholders: check_coverage reads each cell's
        # latitude to allowlist Antarctica. All temperate, so none are excluded.
        self.cells = [h3.latlng_to_cell(10.0 + i, 0.0, 5) for i in range(n_cells)]
        self.airports = ["AAA", "BBB"]
        self.n = n_cells + 2


def _graph(edges: list[tuple[int, int]], n: int = 4) -> sp.csr_matrix:
    """Symmetrised: every edge is added in both directions."""
    rows = [e[0] for e in edges] + [e[1] for e in edges]
    cols = [e[1] for e in edges] + [e[0] for e in edges]
    data = np.ones(len(rows))
    return sp.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()


def _directed(edges: list[tuple[int, int]], n: int = 4) -> sp.csr_matrix:
    """As given, with no symmetrising, so weak and strong connectivity differ.

    Every fixture in this file went through _graph, which makes the two notions
    coincide -- so `connection="weak"` could be changed to `"strong"` and all
    fifteen tests stayed green, while the real graph IS directed (ground hops
    and access/egress are charged asymmetrically) and the check would start
    rejecting most of the network.
    """
    data = np.ones(len(edges))
    return sp.coo_matrix((data, ([e[0] for e in edges], [e[1] for e in edges])),
                         shape=(n, n)).tocsr()


def test_a_fully_wired_graph_passes():
    # c0-c1 adjacent; AAA on c0, BBB on c1; both airports reachable.
    validate.check_airport_connectivity(_TinyGraphIdx(), _graph([(0, 1), (0, 2), (1, 3)]))


def test_an_airport_in_a_severed_component_is_rejected():
    # The c0-c1 hop is gone, so BBB and its cell form their own component.
    # Half the airports are isolated -- far above the 1% bound.
    with pytest.raises(ValueError, match="disconnected"):
        validate.check_airport_connectivity(_TinyGraphIdx(), _graph([(0, 2), (1, 3)]))


def test_weak_connectivity_is_the_notion_used_not_strong():
    """The docstring says why: the graph is directed only because ground hops
    and access/egress are charged asymmetrically, so a node reachable in
    EITHER direction is genuinely wired in. This graph is one-way throughout
    -- c0 -> c1 -> AAA(2) and c1 -> BBB(3) -- so nothing can reach c0 and
    strong connectivity would put every node in its own component and reject
    both airports.
    """
    validate.check_airport_connectivity(
        _TinyGraphIdx(), _directed([(0, 1), (1, 2), (1, 3)]))


def test_a_one_way_graph_with_a_genuinely_severed_airport_is_still_rejected():
    """Weak is not "anything goes": BBB has no edge at all in either
    direction, so it is isolated under both notions."""
    with pytest.raises(ValueError, match="disconnected"):
        validate.check_airport_connectivity(_TinyGraphIdx(), _directed([(0, 1), (1, 2)]))


def test_the_isolated_airports_are_reported_by_name():
    isolated: list[str] = []
    with pytest.raises(ValueError):
        validate.check_airport_connectivity(
            _TinyGraphIdx(), _graph([(0, 2), (1, 3)]), isolated
        )
    assert isolated == ["BBB"]


def test_coverage_alone_would_not_have_caught_it():
    """The reason this gate has to exist at all. The severed component holds
    1 of 2 land cells here; at real scale an orphaned island airport costs a
    few cells out of 548,557, so coverage stays far above MIN_COVERAGE while
    the airport is unreachable from every origin on Earth.
    """
    minutes = np.array([1.0, np.inf])          # c1 unreachable
    idx = _TinyGraphIdx()
    big = np.concatenate([np.full(548_550, 1.0), np.full(7, np.inf)])

    class _Big:
        n_cells = 548_557
        # check_coverage only reads each cell's latitude, so one temperate cell
        # repeated is both faithful and cheap.
        cells = [h3.latlng_to_cell(10.0, 0.0, 5)] * 548_557

    assert validate.check_coverage(minutes, idx) == 0.5
    assert validate.check_coverage(big, _Big()) > validate.MIN_COVERAGE
    with pytest.raises(ValueError, match="disconnected"):
        validate.check_airport_connectivity(idx, _graph([(0, 2), (1, 3)]))


def test_the_gate_keys_on_the_largest_component_not_the_first_airport():
    """Guards the choice of reference component. Here the FIRST airport is the
    orphaned one, so an implementation that took "the component the first
    airport is in" as the main one would invert the verdict -- reporting the
    three-quarters of the graph that is properly wired as disconnected, and the
    orphan as fine.

    Layout: c0-AAA alone (2 nodes); c1-c2-c3-BBB connected (4 nodes).
    """
    idx = _TinyGraphIdx(n_cells=4)          # nodes 0-3 cells, 4 = AAA, 5 = BBB
    csr = _graph([(0, 4), (1, 2), (2, 3), (1, 5)], n=6)

    isolated: list[str] = []
    with pytest.raises(ValueError, match="disconnected"):
        validate.check_airport_connectivity(idx, csr, isolated)
    assert isolated == ["AAA"]


def test_antarctic_cells_are_excluded_from_the_coverage_denominator():
    """Antarctica is charted but has no scheduled service, so every one of its
    cells is unreachable by construction. Counting them would drag a perfect
    build to about 92% -- two points from the gate -- and make the gate mostly a
    measure of how much Antarctica we drew rather than of route coverage.
    """
    class Idx:
        # Two reachable temperate cells, two unreachable Antarctic ones.
        cells: ClassVar[list[str]] = [
            h3.latlng_to_cell(10.0, 0.0, 5),
            h3.latlng_to_cell(11.0, 0.0, 5),
            h3.latlng_to_cell(-75.0, 0.0, 5),
            h3.latlng_to_cell(-76.0, 0.0, 5),
        ]
        n_cells = 4

    minutes = np.array([10.0, 20.0, np.inf, np.inf])
    # Counting Antarctica this would be 0.5; allowlisting it, the two temperate
    # cells are both reachable, so it is 1.0.
    assert validate.check_coverage(minutes, Idx()) == 1.0


def test_an_all_excluded_universe_has_zero_coverage_not_nan():
    """Every cell Antarctic, so nothing is reachable in principle. The mean of
    the empty considered set is NaN, and `NaN < MIN_COVERAGE` is False -- which
    would wave the origin through the gate in cli._solve_one. Zero fails it.
    """
    class Idx:
        cells: ClassVar[list[str]] = [
            h3.latlng_to_cell(-75.0, 0.0, 5),
            h3.latlng_to_cell(-76.0, 0.0, 5),
        ]
        n_cells = 2

    coverage = validate.check_coverage(np.array([10.0, 20.0]), Idx())
    assert coverage == 0.0
    assert coverage < validate.MIN_COVERAGE, "the gate must fail an unmeasurable universe"


def test_the_cover_sample_pull_in_stays_inside_an_antimeridian_cell():
    """The pull-in used to interpolate longitude planarly, so a vertex at
    +179.96 with the centre at -179.95 landed eleven degrees away -- in
    another band or the open sea -- and the gate could fail correct geometry.
    """
    chukotka = "860d9100fffffff"          # straddles 180 E
    clat, clon = h3.cell_to_latlng(chukotka)
    assert abs(abs(clon) - 180.0) < 0.5, "fixture no longer straddles the antimeridian"
    for lon, lat in validate._pulled_in_vertices(chukotka):
        dlon = (lon - clon + 540.0) % 360.0 - 180.0
        assert abs(dlon) < 0.2 and abs(lat - clat) < 0.2, f"sample point {lon:.2f},{lat:.2f} left the cell"


# --- Monotonic gate on the mixed grid (A14) ----------------------------------
#
# hex_edges joins a res-7 cell to the unsplit res-6 cell beyond its ring, both
# ways, and joins the two ends of every road bridge or tunnel in `idx.spans`.
# The gate looked at same-resolution neighbours only, so none of those edges
# was ever checked. Each fixture below puts the inconsistency ONLY on such an
# edge: every same-resolution pair is consistent.


class _MixedIdx:
    """A split res-6 cell (seven res-7 children) ringed by six unsplit ones,
    laid out as graph/refine.refine lays it out: unsplit cells first."""

    def __init__(self):
        from transport_maps.graph import refine
        centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
        base = sorted(h3.grid_disk(centre, 1))
        split = np.array([c == centre for c in base])
        self.cells, self.base_index, self.fine = refine.refine(base, split)
        self.base_cells = base
        self.n_cells = len(self.cells)
        self._pos = {c: i for i, c in enumerate(self.cells)}
        self.severed = frozenset()
        self.spans = {}

    def try_cell_index(self, cell):
        return self._pos.get(cell)


def _monotonic(idx, minutes, **kw):
    """The gate with every input that would need a raster or a parquet given:
    one country, no zones, a flat 50 km/h."""
    n = idx.n_cells
    validate.check_monotonic_ground(idx, minutes, np.full(n, 50.0),
                                    country=np.array(["KOR"] * n), zone=[""] * n, **kw)


def _seam_pairs(idx):
    """(base, fine) positions hex_edges joins across the split seam."""
    from transport_maps.graph import refine
    return [(b, f) for b in np.flatnonzero(~idx.fine) for f in np.flatnonzero(idx.fine)
            if refine.ground_adjacent(idx.cells[f], idx.cells[b])]


def test_a_fine_cell_far_later_than_the_base_cell_beside_it_is_rejected():
    """Base cells at 0 min, every fine child at 1e6. Fine-to-fine and
    base-to-base are consistent; only the seam is not. At the default stride
    only position 0 -- an unsplit base cell -- is sampled, so this is the base
    side's view of the seam, which hex_edges builds from the fine side."""
    idx = _MixedIdx()
    assert _seam_pairs(idx), "fixture: no seam between the split cell and its ring"
    assert not idx.fine[0] and any(b == 0 for b, _ in _seam_pairs(idx)), \
        "fixture: position 0 is not a base cell on the seam"
    minutes = np.where(idx.fine, 1e6, 0.0)
    with pytest.raises(ValueError, match="inconsistent"):
        _monotonic(idx, minutes)


def test_a_base_cell_far_later_than_the_fine_cell_beside_it_is_rejected():
    """The other direction: fine children at 0, base cells at 1e6. The fine
    cells must be sampled to see it, hence stride 1."""
    idx = _MixedIdx()
    minutes = np.where(idx.fine, 0.0, 1e6)
    with pytest.raises(ValueError, match="inconsistent"):
        _monotonic(idx, minutes, stride=1)


def test_consistent_times_on_the_mixed_grid_are_accepted():
    idx = _MixedIdx()
    _monotonic(idx, np.zeros(idx.n_cells), stride=1)       # must not raise


def test_a_severed_seam_pair_is_exempt():
    """Open water across the seam: hex_edges cuts the pair, so the gate must
    not hold the far side to it. Same times as the two rejections above."""
    idx = _MixedIdx()
    idx.severed = frozenset(p for b, f in _seam_pairs(idx) for p in ((b, f), (f, b)))
    _monotonic(idx, np.where(idx.fine, 1e6, 0.0), stride=1)   # must not raise
    _monotonic(idx, np.where(idx.fine, 0.0, 1e6), stride=1)   # must not raise


def test_a_span_end_far_later_than_its_other_end_is_rejected():
    """A bridge joining two cells that are not grid neighbours. Nothing but the
    span joins them, so only the span can show the inconsistency; the control
    with the span's own minutes in hand passes."""
    a = h3.latlng_to_cell(55.5, 11.0, config.SOLVE_RES)
    b = next(c for c in h3.grid_ring(a, 3))

    class Idx:
        cells: ClassVar[list[str]] = [a, b]
        n_cells = 2
        severed = frozenset()
        spans: ClassVar[dict] = {(0, 1): 20.0, (1, 0): 20.0}

        def try_cell_index(self, cell):
            return {a: 0, b: 1}.get(cell)

    with pytest.raises(ValueError, match="inconsistent"):
        _monotonic(Idx(), np.array([0.0, 21.0]))
    _monotonic(Idx(), np.array([0.0, 20.0]))                # must not raise


def test_a_sliver_left_open_at_a_split_seam_is_rejected():
    """Seven fine children do not tile their parent; the parent hexagon painted
    beneath them closes the slivers they leave. With it the native level is
    whole; without it the gate must see the slivers -- which no vertex sample
    can, every vertex being inside its own painted cell (K7)."""
    from shapely.ops import unary_union

    from transport_maps.contour import grid
    from transport_maps.graph import refine
    centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    base = sorted(h3.grid_disk(centre, 2))
    cells, base_index, fine = refine.refine(base, np.array([c == centre for c in base]))

    class Idx:
        pass
    idx = Idx(); idx.cells = cells; idx.n_cells = len(cells)
    idx.base_cells = base; idx.base_index = base_index; idx.fine = fine
    universe, native = grid.universe(base), grid.native_edges(idx)
    lower = _features(_whole(universe[0]).buffer(1e-6))[1:]

    def with_native(geometry):
        return {"features": [_features(geometry)[0], *lower]}

    without_parent = unary_union([_whole([c]) for c in cells])
    with pytest.raises(ValueError, match="level 0"):
        validate.check_bands_cover(idx, universe, native, with_native(without_parent),
                                   samples=len(cells))
    validate.check_bands_cover(idx, universe, native,
                               with_native(without_parent.union(_whole([centre]))),
                               samples=len(cells))    # must not raise
