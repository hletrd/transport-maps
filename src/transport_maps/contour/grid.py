"""The cell universe the map paints: land cells plus rings of sea around them.

Painting only the cells whose centroid is on land leaves every shore an 8 km
hex stair-step -- the land mask can be as fine as it likes, the paint stops
one cell short of it. So the bands run out to sea: each ring inherits the
fastest cell of the ring inside it, and the water layer drawn above the bands
(web/app.js, built by emit/water.py) cuts them back to the real coastline.

Several rings are kept because the low-zoom copies of each band need a wider
sea margin than the high-zoom ones (see contour.bands.LODS). `ring[i]` is 0
for land and r for the r-th ring out; `nb[i, j]` is the position of cell i's
j-th neighbour, or -1 past the outermost ring (or the empty slot of a
pentagon).
"""

from __future__ import annotations

import hashlib

import h3
import numpy as np

from transport_maps import config
from transport_maps.sources._utils import _atomic_write

# Bump when the layout of the cached arrays changes.
GRID_VERSION = "rings-nb6-v2"
# Enough for the coarsest level of detail's margin (bands.LODS) plus one.
RINGS = 4
# Test fixtures of a handful of cells are not worth a cache file each.
MIN_CELLS_TO_CACHE = 5_000
# See graph/ground.EDGE_SLOTS_PER_CELL: the same preallocation, the same guard.
EDGE_SLOTS_PER_CELL = 8


def universe(cells: list[str], rings: int = RINGS) -> tuple[list[str], np.ndarray, np.ndarray]:
    """(all cells, neighbour positions, ring index) for a list of land cells.

    Land cells come first in the order given, then ring 1 sorted, ring 2
    sorted, and so on. Cached on the exact cell list: a different universe of
    the same length must not share an entry.
    """
    cells = list(cells)
    key = hashlib.sha256(f"{GRID_VERSION}|{rings}|{''.join(cells)}".encode()).hexdigest()[:24]
    cached = config.BUILD / f"render-grid-{key}.npz"
    if len(cells) >= MIN_CELLS_TO_CACHE and cached.exists():
        z = np.load(cached, allow_pickle=False)
        sea = [h3.int_to_str(int(v)) for v in z["sea"]]
        return cells + sea, z["nb"], z["ring"]

    seen = set(cells)
    allc = list(cells)
    ring = [0] * len(cells)
    frontier = cells
    for r in range(1, rings + 1):
        grown: set[str] = set()
        for c in frontier:
            for n in h3.grid_ring(c, 1):
                if n not in seen:
                    grown.add(n)
        frontier = sorted(grown)
        seen.update(frontier)
        allc.extend(frontier)
        ring.extend([r] * len(frontier))

    pos = {c: i for i, c in enumerate(allc)}
    nb = np.full((len(allc), 6), -1, dtype=np.int32)
    for i, c in enumerate(allc):
        for j, n in enumerate(h3.grid_ring(c, 1)):
            nb[i, j] = pos.get(n, -1)
    ring_arr = np.asarray(ring, dtype=np.int8)

    if len(cells) >= MIN_CELLS_TO_CACHE:
        sea_ids = np.array([h3.str_to_int(c) for c in allc[len(cells):]], dtype=np.uint64)

        def _save(tmp):
            with open(tmp, "wb") as fh:          # a file object: savez adds no suffix
                np.savez(fh, sea=sea_ids, nb=nb, ring=ring_arr)

        _atomic_write(cached, _save)
    return allc, nb, ring_arr


NATIVE_VERSION = "native-edges-v1"


def native_edges(idx) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Raw adjacency of the index's own (mixed-resolution) cells:
    (rows, cols, complete), directed both ways, no border cuts.

    Fine cells touch the unsplit base cell beyond their ring the same way
    graph/ground.py joins them. `complete[i]` says every ring neighbour of
    cell i was resolved -- the cell is not on the land edge -- which is what
    the coverage gate samples. Cached on the exact cell list.
    """
    cells = list(idx.cells)
    key = hashlib.sha256(f"{NATIVE_VERSION}|{''.join(cells)}".encode()).hexdigest()[:24]
    cached = config.BUILD / f"native-edges-{key}.npz"
    if len(cells) >= MIN_CELLS_TO_CACHE and cached.exists():
        z = np.load(cached, allow_pickle=False)
        return z["rows"], z["cols"], z["complete"]

    pos = {c: i for i, c in enumerate(cells)}
    fine_attr = getattr(idx, "fine", np.zeros(0, dtype=bool))
    fine = fine_attr if len(fine_attr) == len(cells) else np.zeros(len(cells), dtype=bool)
    cap = EDGE_SLOTS_PER_CELL * len(cells)
    rows = np.empty(cap, dtype=np.int32)
    cols = np.empty(cap, dtype=np.int32)
    m = 0
    complete = np.ones(len(cells), dtype=bool)
    cross: set[tuple[int, int]] = set()

    def put(a: int, b: int) -> None:
        nonlocal m
        if m >= cap:
            raise RuntimeError(
                f"native edge capacity exceeded: more than {EDGE_SLOTS_PER_CELL} edges per "
                f"cell over {len(cells):,} cells; raise EDGE_SLOTS_PER_CELL after measuring")
        rows[m] = a; cols[m] = b; m += 1

    for u, c in enumerate(cells):
        for n in h3.grid_ring(c, 1):
            v = pos.get(n)
            if v is not None:
                put(u, v)
                continue
            if fine[u]:
                v = pos.get(h3.cell_to_parent(n, config.SOLVE_RES))
                if v is not None:
                    if (u, v) not in cross:
                        cross.add((u, v))
                        put(u, v)
                        put(v, u)
                    continue
            complete[u] = False
    out = (rows[:m].copy(), cols[:m].copy(), complete)
    if len(cells) >= MIN_CELLS_TO_CACHE:
        def _save(tmp):
            with open(tmp, "wb") as fh:
                np.savez(fh, rows=out[0], cols=out[1], complete=out[2])
        _atomic_write(cached, _save)
    return out
