"""Coarse res-4 time array for instant hover readout.

Layout contract with the frontend: little-endian uint16 minutes, one entry per
res-4 cell, ordered by the sorted res-4 cell id list that `hover_cells` returns.
The frontend fetches that ordering once from index.json.

Each res-4 entry is the MINIMUM over its (up to seven) res-5 children, not an
average or a representative sample -- deliberately: a hover value is meant to
answer "is anywhere in here reachable within X", and a mean would hide a
reachable corner behind a slow one. The cost is that the readout is
systematically optimistic against the band actually painted under the
cursor -- the pmtiles bands are drawn per res-5 cell, so a res-4 tile can show
a faster hover time than the band colour underneath it whenever its children's
times spread across a band edge.
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
        best[p] = min(best[p], cell_minutes[pos])

    encoded = np.where(
        np.isfinite(best), np.minimum(best, MAX_MINUTES), config.UNREACHABLE
    ).astype("<u2")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded.tobytes())
