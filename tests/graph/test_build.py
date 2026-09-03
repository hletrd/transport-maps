import numpy as np
import pytest

from transport_maps.graph import build, nodes


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


def test_neighbouring_land_cells_are_connected(csr, idx):
    import h3
    seoul = h3.latlng_to_cell(37.5665, 126.9780, 5)
    u = idx.cell_index(seoul)
    assert csr[u].nnz >= 2


def test_incheon_reaches_narita_directly(csr, idx):
    u, v = idx.airport_index("ICN"), idx.airport_index("NRT")
    assert csr[u, v] > 0


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
