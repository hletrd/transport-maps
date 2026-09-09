"""The cell universe the map paints: land cells plus their one-ring sea fringe.

Painting only the cells whose centroid is on land leaves every shore an 8 km
hex stair-step -- the land mask can be as fine as it likes, the paint stops
one cell short of it. The fringe ring inherits the fastest adjacent land cell,
so the bands run one cell past the shore, and the water layer drawn above them
(web/app.js, built by emit/water.py) cuts them back to the real coastline.

Also carries every cell's six neighbour positions, which is what lets
`contour.bands` decide in one vectorised pass which cells sit safely inside a
band boundary and which are on its rim.
"""

from __future__ import annotations

import hashlib

import h3
import numpy as np

from transport_maps import config
from transport_maps.sources._utils import _atomic_write

# Bump when the layout of the cached arrays changes.
GRID_VERSION = "ring1-nb6-v1"
# Test fixtures of a handful of cells are not worth a cache file each.
MIN_CELLS_TO_CACHE = 5_000


def universe(cells: list[str]) -> tuple[list[str], np.ndarray]:
    """(all cells, neighbour positions) for a list of land cells.

    The land cells come first, in the order given, then the fringe sorted.
    `nb[i, j]` is the position of cell i's j-th neighbour, or -1 where that
    neighbour is open water beyond the fringe (or the empty slot of a
    pentagon). Cached on the exact cell list: a different universe of the same
    length must not share an entry.
    """
    cells = list(cells)
    key = hashlib.sha256((GRID_VERSION + "|" + "".join(cells)).encode()).hexdigest()[:24]
    cached = config.BUILD / f"render-grid-{key}.npz"
    if len(cells) >= MIN_CELLS_TO_CACHE and cached.exists():
        z = np.load(cached, allow_pickle=False)
        fringe = [h3.int_to_str(int(v)) for v in z["fringe"]]
        return cells + fringe, z["nb"]

    land = set(cells)
    fringe_set: set[str] = set()
    for c in cells:
        for n in h3.grid_ring(c, 1):
            if n not in land:
                fringe_set.add(n)
    fringe = sorted(fringe_set)
    allc = cells + fringe
    pos = {c: i for i, c in enumerate(allc)}
    nb = np.full((len(allc), 6), -1, dtype=np.int32)
    for i, c in enumerate(allc):
        for j, n in enumerate(h3.grid_ring(c, 1)):
            nb[i, j] = pos.get(n, -1)

    if len(cells) >= MIN_CELLS_TO_CACHE:
        fringe_ids = np.array([h3.str_to_int(c) for c in fringe], dtype=np.uint64)

        def _save(tmp):
            with open(tmp, "wb") as fh:          # a file object: savez adds no suffix
                np.savez(fh, fringe=fringe_ids, nb=nb)

        _atomic_write(cached, _save)
    return allc, nb
