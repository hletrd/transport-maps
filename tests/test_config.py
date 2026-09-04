import itertools

from transport_maps import config


def test_band_edges_strictly_increasing():
    edges = config.BAND_EDGES_MIN
    assert len(edges) == 10
    assert all(a < b for a, b in itertools.pairwise(edges))


def test_unreachable_sentinel_fits_uint16_and_exceeds_all_bands():
    assert config.UNREACHABLE == 65535
    assert config.UNREACHABLE > config.BAND_EDGES_MIN[-1]


def test_hover_resolution_is_coarser_than_solve_resolution():
    assert config.HOVER_RES < config.SOLVE_RES
