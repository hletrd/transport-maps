import numpy as np
import pytest

from transport_maps.graph import build, nodes

# Builds the full node index from the cached universe: minutes, real caches.
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


@pytest.fixture(scope="module")
def build_result(idx):
    rejected: list[tuple[str, str, float]] = []
    csr = build.build_graph(idx, rejected)
    return csr, rejected


@pytest.fixture(scope="module")
def csr(build_result):
    return build_result[0]


@pytest.fixture(scope="module")
def rejected_air_pairs(build_result):
    return build_result[1]


def test_matrix_is_square_and_matches_node_count(csr, idx):
    assert csr.shape == (idx.n, idx.n)


def test_all_weights_are_positive_and_finite(csr):
    data = csr.data
    assert np.isfinite(data).all()
    assert (data > 0).all()


def test_duplicate_row_col_pairs_across_edge_parts_are_rejected(monkeypatch):
    """`coo_matrix` SUMS duplicate (row, col) entries instead of keeping the
    cheaper edge, so two edge parts naming the same pair must be caught before
    assembly rather than silently inflating that edge's weight. No part
    produces a duplicate today (the real `csr` fixture proves that below --
    it would never have built if it did), so this injects one directly.
    """
    class FakeIdx:
        n = 3
        has_rail = False

    dup = (np.array([0, 0], dtype=np.int64), np.array([1, 1], dtype=np.int64), np.array([5.0, 3.0]))
    empty = (np.array([], dtype=np.int64), np.array([], dtype=np.int64), np.array([], dtype=np.float64))
    monkeypatch.setattr(build.ground, "hex_edges", lambda idx: dup)
    monkeypatch.setattr(build, "_air_edges", lambda *args, **kwargs: empty)
    monkeypatch.setattr(build, "_access_edges", lambda idx: empty)
    monkeypatch.setattr(build, "_transfer_edges", lambda idx: empty)

    with pytest.raises(RuntimeError, match="duplicate"):
        build.build_graph(FakeIdx())


def test_neighbouring_land_cells_are_connected(csr, idx):
    # The index decides whether Seoul's cell is a base cell or a fine child
    # of a split one; a literal resolution here went stale when the grid
    # moved from res 5 to res 6/7.
    seoul = idx.cell_at(37.5665, 126.9780)
    u = idx.cell_index(seoul)
    assert csr[u].nnz >= 2


def test_incheon_reaches_narita_directly(csr, idx):
    # A flight lands on the arrival node, never the departure node: that split
    # is what stops a journey's first flight paying a connection penalty.
    u = idx.airport_index("ICN")
    assert csr[u, idx.airport_arr_index("NRT")] > 0
    assert csr[u, idx.airport_index("NRT")] == 0


def test_implausible_longhaul_pair_between_small_airports_is_rejected():
    # A 14,000 km pair between two medium airports has no real-world analogue
    # (no scheduled aircraft flies that far without a large hub at one end) --
    # this is the shape of the Wikidata resolution error that fabricated
    # Lasondre_Airport -> LSE (Indonesia -> Wisconsin).
    assert not build.is_geographically_plausible(14000.0, "medium", "medium")


def test_implausible_longhaul_pair_with_a_large_airport_is_kept():
    # Same distance, but a large airport at one end: real long-haul routes
    # like SYD->LHR look exactly like this and must not be rejected.
    assert build.is_geographically_plausible(14000.0, "large", "medium")


def test_geographic_plausibility_guard_rejects_a_small_but_nonzero_count(rejected_air_pairs):
    # Pinned against the live route network: exactly 6 directed pairs today
    # (all via a Wikidata P238 resolution error routing through LSE, IWA, or
    # AZA -- see build.is_geographically_plausible). This count is expected to
    # drift when the route network is refreshed, so the bound below is loose
    # on purpose rather than pinned to 6. Investigate before assuming a new
    # count is fine: 0 means the guard silently stopped rejecting anything
    # (e.g. a broken size lookup), and a jump into the hundreds means it
    # started over-rejecting real long-haul routes.
    assert 1 <= len(rejected_air_pairs) <= 20


@pytest.fixture(scope="module")
def unknown_airport_pairs(idx):
    unknown: list[tuple[str, str]] = []
    build.build_graph(idx, None, unknown)
    return unknown


def test_route_pairs_naming_an_unknown_airport_are_counted(unknown_airport_pairs, idx):
    """These pairs reference airports the land mask had no cell for, so they
    cannot become edges. The skip used to be silent and unbounded: a land-mask
    regression would have deleted the air network one pair at a time with only
    the land-CELL coverage gate in the way.

    124 today, all downstream of the 25 dropped airports. Loose on purpose --
    investigate rather than adjust if it moves far.
    """
    from transport_maps.sources import routes

    total = len(routes.route_network())
    assert 0 < len(unknown_airport_pairs) <= build.MAX_UNKNOWN_PAIR_FRACTION * total
    # Every dropped pair must name an airport that really is absent, rather
    # than the count being padded by pairs that should have been edges.
    known = set(idx.airports)
    assert all(s not in known or d not in known for s, d in unknown_airport_pairs)


def test_the_real_graph_passes_the_airport_connectivity_gate(csr, idx):
    """The gate has to hold against the live network, not just the doubles in
    tests/test_validate.py. 9 of 3,983 airports are isolated today (0.23%),
    all small-island fields with no resolvable destinations.
    """
    from transport_maps import validate

    isolated: list[str] = []
    validate.check_airport_connectivity(idx, csr, isolated)
    assert 0 <= len(isolated) <= validate.MAX_ISOLATED_AIRPORT_FRACTION * len(idx.airports)
