"""Coarse res-4 time array for instant hover readout.

Layout contract with the frontend: little-endian uint16 minutes, one entry per
res-4 cell, ordered by the sorted res-4 cell id list that `hover_cells` returns.
The frontend fetches that ordering once from index.json.

Each res-4 entry is the value of its CENTRE res-5 child (the fastest child
only where the centre is water). An earlier version took the minimum over all
seven children, which made the readout systematically optimistic and, worse,
let it borrow across borders: South Korean times ten kilometres inside the
North, the Singapore side of the strait for Johor Bahru.
"""

from pathlib import Path

import h3
import numpy as np

from transport_maps import config

# Reserve the sentinel; anything slower is clamped to just below it.
MAX_MINUTES = config.UNREACHABLE - 1


def hover_cells(idx) -> list[str]:
    """Sorted res-4 parents of the solver cells."""
    return sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})


def _representative_children(idx, parents: list[str], cell_minutes: np.ndarray) -> dict[int, int]:
    """For each res-4 parent, the res-5 child the readout should report.

    The CENTRE child where it is on land, else the fastest child. Taking the
    minimum everywhere made the readout "the best time anywhere within ~22 km",
    which read South Korean times ten kilometres inside North Korea and put
    Johor Bahru at 21 minutes from Singapore by borrowing the Singapore side
    of the strait. The centre child is what a pointer at that spot means.
    """
    position = {cell: i for i, cell in enumerate(parents)}
    cell_pos = {c: i for i, c in enumerate(idx.cells)}
    picked: dict[int, int] = {}
    # fastest child as the fallback for parents whose centre is water
    best_pos: dict[int, int] = {}
    for pos, cell in enumerate(idx.cells):
        p = position[h3.cell_to_parent(cell, config.HOVER_RES)]
        if p not in best_pos or cell_minutes[pos] < cell_minutes[best_pos[p]]:
            best_pos[p] = pos
    for p, parent in enumerate(parents):
        centre = h3.cell_to_center_child(parent, config.SOLVE_RES)
        pos = cell_pos.get(centre)
        if pos is None:
            # The base cell at the centre was split: take its own centre child.
            pos = cell_pos.get(h3.cell_to_center_child(parent, config.FINE_RES))
        picked[p] = best_pos[p] if pos is None else pos
    return picked


def write_hover(idx, cell_minutes: np.ndarray, out: Path) -> None:
    parents = hover_cells(idx)

    best = np.full(len(parents), np.inf, dtype=np.float64)
    picked = _representative_children(idx, parents, cell_minutes)
    for p, pos in picked.items():
        best[p] = cell_minutes[pos]

    encoded = np.where(
        np.isfinite(best), np.minimum(best, MAX_MINUTES), config.UNREACHABLE
    ).astype("<u2")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded.tobytes())
