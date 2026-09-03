import numpy as np
import pytest

from transport_maps.graph import build, nodes


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


@pytest.fixture(scope="module")
def csr(idx):
    return build.build_graph(idx)


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
