import h3
import numpy as np

from transport_maps.contour import grid


def test_rings_are_the_successive_rings_of_sea_around_land():
    centre = h3.latlng_to_cell(37.5, 127.0, 5)
    land = sorted(h3.grid_disk(centre, 1))
    cells, nb, ring = grid.universe(land, rings=3)
    assert cells[: len(land)] == land
    assert (ring[: len(land)] == 0).all()
    for r in (1, 2, 3):
        assert set(np.array(cells, dtype=object)[ring == r]) == set(h3.grid_ring(centre, r + 1))
    assert nb.shape == (len(cells), 6)


def test_neighbour_table_is_symmetric_and_open_sea_is_minus_one():
    centre = h3.latlng_to_cell(37.5, 127.0, 5)
    land = sorted(h3.grid_disk(centre, 1))
    cells, nb, ring = grid.universe(land, rings=2)
    for i in range(len(cells)):
        for j in nb[i]:
            if j >= 0:
                assert i in nb[j], "neighbour relation must be mutual"
    # Everything but the outermost ring has all six neighbours in the universe.
    assert (nb[ring < 2] >= 0).all()
    # The outermost ring touches the ring inside it and open sea.
    outer = nb[ring == 2]
    assert ((outer >= 0) & (ring[np.maximum(outer, 0)] == 1)).any(axis=1).all()
    assert (outer == -1).any(axis=1).all()


def test_cache_is_keyed_on_the_exact_cell_list(tmp_path, monkeypatch):
    monkeypatch.setattr(grid.config, "BUILD", tmp_path)
    monkeypatch.setattr(grid, "MIN_CELLS_TO_CACHE", 1)
    a = sorted(h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, 5), 1))
    b = sorted(h3.grid_disk(h3.latlng_to_cell(48.8, 2.3, 5), 1))
    ca, nba, ra = grid.universe(a)
    grid.universe(b)
    assert len(list(tmp_path.glob("render-grid-*.npz"))) == 2, "same-length universes shared a cache entry"
    ca2, nba2, ra2 = grid.universe(a)
    assert ca2 == ca and np.array_equal(nba2, nba) and np.array_equal(ra2, ra)
