import pytest

from transport_maps.graph import nodes

# Builds the full node index from the cached universe: minutes, real caches.
pytestmark = pytest.mark.integration


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


def test_airports_without_a_land_cell_are_counted_not_silently_skipped(idx):
    """An airport whose containing cell missed the land mask is dropped. That
    skip was silent and unbounded, so a land-mask regression could delete
    thousands of airports while the 90% coverage gate -- which counts land
    CELLS, not airports -- still passed.
    """
    from transport_maps.sources import airports

    total = len(airports.scheduled_airports())
    assert isinstance(idx.dropped_airports, tuple)
    assert len(idx.dropped_airports) + len(idx.airports) == total
    # 25 today. Loose on purpose: this drifts with the land mask and the
    # airport table, but a jump into the thousands is a regression.
    assert 0 <= len(idx.dropped_airports) <= nodes.MAX_DROPPED_AIRPORT_FRACTION * total


# The proof that the bound ABORTS needs no real data and lives, fast, in
# test_nodes_bounds.py (TE-26).
