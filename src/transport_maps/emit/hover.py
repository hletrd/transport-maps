"""Coarse res-4 time array for instant hover readout.

Layout contract with the frontend: little-endian uint16 minutes, one entry per
res-4 cell, ordered by the sorted res-4 cell id list that `hover_cells` returns.
The frontend fetches that ordering once from index.json.
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


def write_hover(idx, cell_minutes: np.ndarray, out: Path) -> None:
    parents = hover_cells(idx)
    position = {cell: i for i, cell in enumerate(parents)}

    best = np.full(len(parents), np.inf, dtype=np.float64)
    for pos, cell in enumerate(idx.cells):
        p = position[h3.cell_to_parent(cell, config.HOVER_RES)]
        value = cell_minutes[pos]
        if value < best[p]:
            best[p] = value

    encoded = np.where(
        np.isfinite(best), np.minimum(best, MAX_MINUTES), config.UNREACHABLE
    ).astype("<u2")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded.tobytes())
