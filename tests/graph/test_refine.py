import h3
import numpy as np

from transport_maps import config
from transport_maps.graph import refine


def test_dense_where_roads_are_good_or_a_city_is_near():
    cls = np.array([0, 1, 2, 3, 4, 5, 0])
    urban = np.array([False, False, False, False, False, False, True])
    assert refine.dense_mask(cls, urban).tolist() == [False, True, True, True, False, False, True]


def test_split_cells_become_their_seven_children_and_keep_their_base_index():
    base = sorted(h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES), 1))
    split = np.zeros(len(base), dtype=bool)
    split[2] = True
    cells, base_index, fine = refine.refine(base, split)
    assert len(cells) == len(base) - 1 + 7
    assert not fine[: len(base) - 1].any() and fine[len(base) - 1:].all()
    kids = [c for c, f in zip(cells, fine) if f]
    assert all(h3.get_resolution(c) == config.FINE_RES for c in kids)
    assert all(h3.cell_to_parent(c, config.SOLVE_RES) == base[2] for c in kids)
    assert (base_index[fine] == 2).all()
    # unsplit cells map to themselves
    for c, i in zip(cells[: len(base) - 1], base_index[: len(base) - 1]):
        assert base[i] == c


def test_base_values_carry_down_to_children():
    base = sorted(h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES), 1))
    split = np.zeros(len(base), dtype=bool); split[0] = True
    cells, base_index, fine = refine.refine(base, split)

    class Idx:
        pass
    idx = Idx(); idx.base_index = base_index
    values = np.arange(len(base)) * 10
    out = refine.expand(values, idx)
    assert len(out) == len(cells)
    assert (out[fine] == 0).all()
    assert out[0] == values[base_index[0]]
