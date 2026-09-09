import h3
import numpy as np

from transport_maps.contour import grid


def test_fringe_is_exactly_the_one_ring_of_sea_around_land():
    centre = h3.latlng_to_cell(37.5, 127.0, 5)
    land = sorted(h3.grid_disk(centre, 1))
    cells, nb = grid.universe(land)
    assert cells[: len(land)] == land
    fringe = set(cells[len(land):])
    assert fringe == set(h3.grid_ring(centre, 2))
    assert nb.shape == (len(cells), 6)


def test_neighbour_table_is_symmetric_and_open_sea_is_minus_one():
    centre = h3.latlng_to_cell(37.5, 127.0, 5)
    land = sorted(h3.grid_disk(centre, 1))
    cells, nb = grid.universe(land)
    n_land = len(land)
    for i in range(len(cells)):
        for j in nb[i]:
            if j >= 0:
                assert i in nb[j], "neighbour relation must be mutual"
    # Every land cell of a 7-disk has all six neighbours inside land+fringe.
    assert (nb[:n_land] >= 0).all()
    # Every fringe cell touches at least one land cell and at least one gap.
    assert ((nb[n_land:] >= 0) & (nb[n_land:] < n_land)).any(axis=1).all()
    assert (nb[n_land:] == -1).any(axis=1).all()


def test_cache_is_keyed_on_the_exact_cell_list(tmp_path, monkeypatch):
    monkeypatch.setattr(grid.config, "BUILD", tmp_path)
    monkeypatch.setattr(grid, "MIN_CELLS_TO_CACHE", 1)
    a = sorted(h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, 5), 1))
    b = sorted(h3.grid_disk(h3.latlng_to_cell(48.8, 2.3, 5), 1))
    ca, nba = grid.universe(a)
    cb, nbb = grid.universe(b)
    assert len(list(tmp_path.glob("render-grid-*.npz"))) == 2, "same-length universes shared a cache entry"
    ca2, nba2 = grid.universe(a)
    assert ca2 == ca and np.array_equal(nba2, nba)
