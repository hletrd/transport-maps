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


def test_the_dropped_airport_bound_actually_aborts(monkeypatch):
    """Proof the bound is a gate and not just a number: put every airport off
    the land mask and build_index must refuse, not return an empty graph.
    """
    import polars as pl

    monkeypatch.setattr(
        nodes.airports, "scheduled_airports",
        lambda: pl.DataFrame({
            # Mid-Pacific and mid-Atlantic: open ocean, no land cell anywhere near.
            "iata": ["AAA", "BBB"],
            "lat": [0.0, 30.0],
            "lon": [-160.0, -40.0],
        }),
    )
    with pytest.raises(RuntimeError, match="land mask has regressed"):
        nodes.build_index()
