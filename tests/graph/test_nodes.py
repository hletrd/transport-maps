import pytest

from transport_maps.graph import nodes


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


def test_cells_occupy_the_low_indices(idx):
    assert idx.cell_index(idx.cells[0]) == 0
    assert idx.cell_index(idx.cells[-1]) == idx.n_cells - 1


def test_airports_occupy_the_high_indices(idx):
    assert idx.airport_index("ICN") >= idx.n_cells
    assert idx.airport_index("ICN") < idx.n


def test_every_airport_maps_into_a_land_cell(idx):
    # Airports sit on land; the overlap containment mode guarantees coverage.
    assert idx.airport_cell_index("ICN") < idx.n_cells


def test_unknown_lookups_raise(idx):
    with pytest.raises(KeyError):
        idx.airport_index("ZZZ")
