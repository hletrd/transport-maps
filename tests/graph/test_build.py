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
