import h3
import numpy as np

from transport_maps import config
from transport_maps.contour import grid
from transport_maps.graph import refine


def _mixed():
    base = sorted(h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES), 2))
    centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    split = np.array([c == centre for c in base])
    cells, base_index, fine = refine.refine(base, split)

    class Idx:
        pass
    idx = Idx(); idx.cells = cells; idx.n_cells = len(cells)
    idx.base_cells = base; idx.base_index = base_index; idx.fine = fine
    return idx


def test_fine_cells_are_joined_to_the_unsplit_cell_beyond_their_ring():
    idx = _mixed()
    rows, cols, complete = grid.native_edges(idx)
    fine_pos = set(np.flatnonzero(idx.fine).tolist())
    # every fine cell on the outer edge of the split cell has a base neighbour
    cross = {(int(u), int(v)) for u, v in zip(rows, cols) if u in fine_pos and v not in fine_pos}
    assert cross, "no fine-to-base adjacency"
    # and each such edge exists in both directions
    for u, v in cross:
        assert (v, u) in {(int(a), int(b)) for a, b in zip(rows, cols)}
    # every cross pair appears exactly once per direction (coo_matrix would sum duplicates)
    pairs = list(zip(rows.tolist(), cols.tolist()))
    assert len(pairs) == len(set(pairs))
    # the centre of the disk is complete; the outer ring is not
    assert complete[idx.fine].all()
    assert not complete[[i for i, c in enumerate(idx.cells)
                         if not idx.fine[i] and h3.grid_distance(c, h3.cell_to_parent(idx.cells[list(fine_pos)[0]], config.SOLVE_RES)) == 2]].any()
