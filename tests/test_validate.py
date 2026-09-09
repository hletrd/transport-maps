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
        cells = [h3.latlng_to_cell(10.0 + i, 0.0, 5) for i in range(4)]
    assert validate.check_coverage(minutes, Idx()) == 0.5


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
        cells = [h3.latlng_to_cell(10.0 + i, 0.0, 5) for i in range(100)]
    assert validate.check_coverage(minutes, Idx()) < validate.MIN_COVERAGE


def _hex_universe():
    """A 19-cell disk and its neighbour table, the shape the gate expects."""
    from transport_maps.contour import grid
    centre = h3.latlng_to_cell(37.5, 127.0, 5)
    return grid.universe(sorted(h3.grid_disk(centre, 2)))


def _feature(geom, band=0):
    from shapely.geometry import mapping
    return {"properties": {"band": band}, "geometry": mapping(geom)}


def test_a_hole_between_bands_is_rejected():
    """The gate must see a gap at an interior hex vertex, not just at centroids."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    cells, nb = _hex_universe()
    whole = unary_union([Polygon([(lo, la) for la, lo in h3.cell_to_boundary(c)]) for c in cells])
    # Punch out a disc around one vertex of the CENTRE cell -- an interior vertex.
    la, lo = h3.cell_to_boundary(cells[len(cells) // 2])[0]
    holed = whole.difference(Point(lo, la).buffer(0.002))
    with pytest.raises(ValueError, match="between bands"):
        validate.check_bands_cover(cells, nb, {"features": [_feature(holed)]}, samples=len(cells))


def test_full_coverage_is_accepted():
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    cells, nb = _hex_universe()
    whole = unary_union([Polygon([(lo, la) for la, lo in h3.cell_to_boundary(c)]) for c in cells])
    validate.check_bands_cover(cells, nb, {"features": [_feature(whole.buffer(1e-6))]},
                               samples=len(cells))  # must not raise


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
        validate.check_monotonic_ground(idx, minutes, ground.cell_speed_kmh(idx))


def test_consistent_neighbour_time_is_accepted():
    """Sanity companion to the rejection test: a neighbour time within the
    real hop cost of its already-reached neighbour must not raise.
    """
    cell, neighbour = _adjacent_pair()
    idx = _TwoCellIdx(cell, neighbour)
    minutes = np.array([0.0, 0.0])  # reaching the neighbour "for free" only helps

    # must not raise
    validate.check_monotonic_ground(idx, minutes, ground.cell_speed_kmh(idx))


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
    rows = [e[0] for e in edges] + [e[1] for e in edges]
    cols = [e[1] for e in edges] + [e[0] for e in edges]
    data = np.ones(len(rows))
    return sp.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()


def test_a_fully_wired_graph_passes():
    # c0-c1 adjacent; AAA on c0, BBB on c1; both airports reachable.
    validate.check_airport_connectivity(_TinyGraphIdx(), _graph([(0, 1), (0, 2), (1, 3)]))


def test_an_airport_in_a_severed_component_is_rejected():
    # The c0-c1 hop is gone, so BBB and its cell form their own component.
    # Half the airports are isolated -- far above the 1% bound.
    with pytest.raises(ValueError, match="disconnected"):
        validate.check_airport_connectivity(_TinyGraphIdx(), _graph([(0, 2), (1, 3)]))


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
        cells = [
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
