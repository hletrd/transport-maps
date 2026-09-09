"""Where the grid is finer.

The base grid is resolution 6, cells about 5.6 km across. Where people
actually are -- East Asia, South Asia, Europe, the United States and every
other built-up region -- that is coarse: a city block of Seoul and the hill
behind it share one cell, and a border or a coast steps by 5 km. Those cells
are split into their seven resolution-7 children, 2.1 km across.

"Dense" is decided by data, not by drawing boxes around continents: a cell is
split where the road network reaches highway, primary or secondary grade
(GRIP4 class 1-3), or where it lies inside a metropolitan area (the urban
mask). That follows population wherever it is, and leaves the Sahara, the
taiga and the outback on the base grid, where finer cells would only cost.
"""

from __future__ import annotations

import h3
import numpy as np

from transport_maps import config

# GRIP4 classes: 0 roadless, 1 highway, 2 primary, 3 secondary, 4 tertiary,
# 5 local. Splitting at tertiary would pull in most of the temperate world.
SPLIT_MAX_CLASS = 3


def dense_mask(cell_class: np.ndarray, urban: np.ndarray) -> np.ndarray:
    """Which base cells to split."""
    cls = np.asarray(cell_class)
    return np.asarray(urban, dtype=bool) | ((cls >= 1) & (cls <= SPLIT_MAX_CLASS))


def refine(base_cells: list[str], split: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray]:
    """(mixed cells, base index of each, is-fine flag).

    Unsplit base cells keep their order and come first; the children of split
    cells follow, grouped by parent. `base_index[i]` is the position in
    `base_cells` of cell i's base-resolution self or parent, which is how
    per-base-cell inputs (road class, urban mask) are carried down without
    being recomputed for millions of children.
    """
    keep = np.flatnonzero(~split)
    cells = [base_cells[i] for i in keep]
    base_index = list(keep)
    for i in np.flatnonzero(split):
        kids = h3.cell_to_children(base_cells[i], config.FINE_RES)
        cells.extend(kids)
        base_index.extend([i] * len(kids))
    base_index = np.asarray(base_index, dtype=np.int64)
    fine = np.zeros(len(cells), dtype=bool)
    fine[len(keep):] = True
    return cells, base_index, fine


def base_parent(cell: str) -> str:
    """The base-resolution cell containing `cell` (itself when already base)."""
    return cell if h3.get_resolution(cell) == config.SOLVE_RES else h3.cell_to_parent(cell, config.SOLVE_RES)


def expand(base_values: np.ndarray, idx) -> np.ndarray:
    """Per-base-cell values carried down to every cell of the index."""
    return np.asarray(base_values)[idx.base_index]


def ground_adjacent(a: str, b: str) -> bool:
    """Whether graph/ground.hex_edges joins two cells of the mixed grid.

    Neighbours at the same resolution; or a fine cell and the unsplit base
    cell that one of its ring-1 neighbours falls in -- exactly the pair
    hex_edges adds across a split boundary. Judged the same way so that a
    ferry between such a pair is the duplicate of a ground edge (which
    build_graph refuses) and a ferry between any other pair is a real
    crossing, both here and when emit/modes books the leg. An earlier
    version compared base parents (equal or neighbouring), which called fine
    cells up to two base cells apart "adjacent" and silently dropped the
    ferries between them.
    """
    ra, rb = h3.get_resolution(a), h3.get_resolution(b)
    if ra == rb:
        return h3.are_neighbor_cells(a, b)
    fine, base = (a, b) if ra > rb else (b, a)
    return any(h3.cell_to_parent(n, min(ra, rb)) == base for n in h3.grid_ring(fine, 1))
