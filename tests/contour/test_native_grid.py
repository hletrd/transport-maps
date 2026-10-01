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


def test_the_native_cache_is_read_back_not_recomputed(tmp_path, monkeypatch):
    """The cached branch is what every real build takes (13.8 million cells,
    a 671 MB file), and the size rule kept every fixture off it (S5, ARCH-13).
    `cache=True` forces it on 25 cells. The file is then overwritten with a
    payload no computation would produce, so a second call can only return it
    by READING the file -- a recompute returns the true arrays, which is why
    comparing two calls proves nothing (TE3-7 is that mistake in `universe`).

    Mutations performed and reverted, each -> red: the read branch made
    `if False:` (the doctored payload is not returned); the saved key `rows`
    renamed `row` (KeyError on read); the write skipped (no file).
    """
    monkeypatch.setattr(grid.config, "BUILD", tmp_path)
    idx = _mixed()
    rows, cols, complete = grid.native_edges(idx, cache=True)
    files = list(tmp_path.glob("native-edges-*.npz"))
    assert len(files) == 1, "cache=True wrote no cache file"
    # What the writer wrote, the reader can read: same arrays back.
    for got, want in zip(grid.native_edges(idx, cache=True), (rows, cols, complete)):
        assert np.array_equal(got, want)

    doctored = (rows[::-1].copy(), cols[::-1].copy(), ~complete)
    np.savez(files[0], rows=doctored[0], cols=doctored[1], complete=doctored[2])
    again = grid.native_edges(idx, cache=True)
    for got, want in zip(again, doctored):
        assert np.array_equal(got, want), "the cached file was not read"

    # Keyed on the exact cell list: another universe neither reads this file
    # nor overwrites it.
    other = _mixed()
    other.cells = other.cells[:-1]
    grid.native_edges(other, cache=True)
    assert len(list(tmp_path.glob("native-edges-*.npz"))) == 2


def test_the_size_rule_still_decides_when_no_one_asks(tmp_path, monkeypatch):
    """`cache=None` must behave exactly as before -- a 25-cell fixture writes
    nothing -- and `cache=False` must hold even above the threshold.

    Mutation performed and reverted: `use_cache = True` regardless of `cache`
    -> red (a file appears).
    """
    monkeypatch.setattr(grid.config, "BUILD", tmp_path)
    idx = _mixed()
    assert len(idx.cells) < grid.MIN_CELLS_TO_CACHE
    grid.native_edges(idx)
    assert not list(tmp_path.glob("native-edges-*.npz"))

    monkeypatch.setattr(grid, "MIN_CELLS_TO_CACHE", 1)
    grid.native_edges(idx, cache=False)
    assert not list(tmp_path.glob("native-edges-*.npz"))
    grid.native_edges(idx)
    assert len(list(tmp_path.glob("native-edges-*.npz"))) == 1, "the size rule stopped applying"


def test_the_unsplit_side_of_a_seam_is_complete():
    """A base cell whose ring neighbour was split finds that neighbour absent
    from the index -- its children are there instead, joined to it from their
    side. It is resolved, not on the land edge, and the cover gate samples
    only `complete` cells; counted incomplete, no cell on the unsplit side of
    any seam was ever sampled (TR-11 / K7)."""
    idx = _mixed()
    _rows, _cols, complete = grid.native_edges(idx)
    centre = h3.cell_to_parent(idx.cells[int(np.flatnonzero(idx.fine)[0])], config.SOLVE_RES)
    seam = [i for i, c in enumerate(idx.cells)
            if not idx.fine[i] and h3.grid_distance(c, centre) == 1]
    assert len(seam) == 6, "fixture: the split cell is not ringed by six unsplit ones"
    assert complete[seam].all(), "the unsplit side of the seam is still counted incomplete"
