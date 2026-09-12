"""The two time grids a visitor's pointer reads.

**Tier A -- `{slug}.bin`, resolution `HOVER_RES`.** A coarse res-4 array,
90,740 entries. It is not only the time readout: one ordinal from it addresses
the arrival-airport array, the mode breakdown and the rail detail as well
(`web/app.js`: `cellIndex`), and the departure card's reach percentages scan
it end to end. That is why it survives tier B rather than being replaced --
re-emitting all four at res 6 costs 90.1 MB per origin (measured).

Layout contract with the frontend: little-endian uint16 minutes, one entry per
res-4 cell, ordered by the sorted res-4 cell id list that `hover_cells`
returns. The frontend fetches that ordering once from index.json.

Each res-4 entry is the value of its CENTRE child at SOLVE_RES -- or, where
that base cell was split, of the FINE_RES centre child -- and of the fastest
child only where the centre is water. An earlier version took the minimum over
all the children, which made the readout systematically optimistic and, worse,
let it borrow across borders: South Korean times ten kilometres inside the
North, the Singapore side of the strait for Johor Bahru.

**Tier B -- `{slug}.r6.bin`, resolution `READING_RES`.** The number the page
actually prints, on the grid the base band is painted from. It is stored as
fixed-width blocks of `READING_SLOTS` uint16 minutes keyed by res-3 parent, in
digit order, so the slot of a cell within its block is ARITHMETIC and no
per-origin cell-id list is needed at all -- the 32.7 MB index a flat res-6
array would have required does not exist. The parent ordering ships once for
the whole site as `reading_parents.bin`, shared by every origin because the
block set is identical across origins and only the values differ.

The block stride is the constant `READING_SLOTS` (343) even though the two
res-3 PENTAGONS that hold land have 286 descendants, not 343. A variable
stride would shift 13,944 of the 14,598 blocks by 57 or 114 slots: in range,
plausible, and silently wrong almost everywhere. Padding -- pentagon holes and
the res-6 cells inside a land-touching parent that are not themselves land,
18.3% of the array -- is written as `config.UNREACHABLE`, so a padding slot
reads as "no route" rather than as a time.
"""

from dataclasses import dataclass
from pathlib import Path

import h3
import numpy as np

from transport_maps import _io, config

# uint16 holds 65,535, the sentinel. Anything at or beyond 65,534 minutes (45
# days) is emitted AS the sentinel: a journey that long is "no route" on the
# page, not "45 days 12 h", and the page treats >= MAX_MINUTES the same way.
MAX_MINUTES = config.UNREACHABLE - 1

# --- H3 bit layout -----------------------------------------------------------
# An h3 v4 cell id packs the resolution in bits 52-55 and fifteen 3-bit digits
# below it, digit r occupying bits (45-3r)..(47-3r). Unused digits are all-ones.
# Working on the ints lets the whole 4,091,715-cell mapping be built with numpy
# instead of four million Python calls into h3; `tests/emit/test_reading.py`
# pins every one of these helpers against h3's OWN cell_to_parent and
# cell_to_children, over both land pentagons, so the fast path cannot drift
# away from the library it is imitating.
_RES_SHIFT = np.uint64(52)
_RES_MASK = np.uint64(0xF)
_MAX_RES = 15


def _digit_shift(res: int) -> np.uint64:
    return np.uint64(45 - 3 * res)


def _to_res(ids: np.ndarray, res: int) -> np.ndarray:
    """Coarsen cell ids to `res`: h3's cell_to_parent, vectorised."""
    out = (ids & ~(_RES_MASK << _RES_SHIFT)) | (np.uint64(res) << _RES_SHIFT)
    for r in range(res + 1, _MAX_RES + 1):
        out = out | (np.uint64(7) << _digit_shift(r))
    return out


def _slots(ids: np.ndarray, parent_res: int, res: int) -> np.ndarray:
    """Position of each cell inside its `parent_res` block, 0 .. 7**(res-parent_res)-1.

    The digits BELOW the parent's resolution, read as a base-7 number. This is
    a bijection onto 0..342 over all 4,091,715 res-6 land cells including the
    two pentagon parents' children (verified); h3's own `cell_to_child_pos`
    is NOT, because it renumbers around a pentagon's deleted subsequence.
    """
    out = np.zeros(len(ids), dtype=np.int64)
    for r in range(parent_res + 1, res + 1):
        out = out * 7 + ((ids >> _digit_shift(r)) & np.uint64(7)).astype(np.int64)
    return out


def reading_slot(cell: str) -> int:
    """The block slot of one cell, for readers and tests."""
    ids = np.array([h3.str_to_int(cell)], dtype=np.uint64)
    return int(_slots(ids, config.READING_PARENT_RES, config.READING_RES)[0])


# --- tier A ------------------------------------------------------------------
def hover_cells(idx) -> list[str]:
    """Sorted res-4 parents of the solver cells."""
    return sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})


def _representative_children(idx, parents: list[str], cell_minutes: np.ndarray) -> dict[int, int]:
    """For each res-4 parent, the solver cell the readout should report.

    The CENTRE child where it is on land, else the fastest child. Taking the
    minimum everywhere made the readout "the best time anywhere within ~45 km",
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


def _encode(values: np.ndarray) -> np.ndarray:
    """Minutes to the shipped uint16, sentinel included."""
    return np.where(
        np.isfinite(values) & (values < MAX_MINUTES), values, config.UNREACHABLE
    ).astype("<u2")


def write_hover(idx, cell_minutes: np.ndarray, out: Path) -> None:
    parents = hover_cells(idx)

    best = np.full(len(parents), np.inf, dtype=np.float64)
    picked = _representative_children(idx, parents, cell_minutes)
    for p, pos in picked.items():
        best[p] = cell_minutes[pos]

    _io.write_bytes(out, _encode(best).tobytes())


# --- tier B ------------------------------------------------------------------
@dataclass(frozen=True)
class ReadingLayout:
    """Where every base cell's minutes go in the block array.

    Built ONCE per build and carried into the fork pool, because it depends
    only on the grid and not on any origin: the mapping is the same 4,091,715
    entries for all 553 origins, and rebuilding it per origin would cost the
    build hours for an answer that cannot change.
    """

    parents: list[str]
    #: For every position in `idx.base_cells`, its index in the flat block
    #: array -- block * READING_SLOTS + slot.
    dest: np.ndarray
    #: For every position in `idx.base_cells`, the position in `idx.cells`
    #: whose minutes it takes, or -1 where the grid has none.
    source: np.ndarray

    @property
    def n_slots(self) -> int:
        return len(self.parents) * config.READING_SLOTS

    @property
    def nbytes(self) -> int:
        return self.n_slots * 2


def reading_parents(idx) -> list[str]:
    """Sorted res-3 parents of the base grid: the shared block ordering.

    Derived from `idx.base_cells`, the uniform res-`READING_RES` grid, so the
    parent set covers exactly the cells tier B has values for. The res-4
    parents of that same set are exactly `hover_cells(idx)`, which is what
    lets the page hold both tiers without either covering ground the other
    does not.
    """
    ids = np.array([h3.str_to_int(c) for c in idx.base_cells], dtype=np.uint64)
    return [h3.int_to_str(int(v)) for v in np.unique(_to_res(ids, config.READING_PARENT_RES))]


def reading_layout(idx) -> ReadingLayout:
    ids = np.array([h3.str_to_int(c) for c in idx.base_cells], dtype=np.uint64)
    parent_ids = np.unique(_to_res(ids, config.READING_PARENT_RES))
    block = np.searchsorted(parent_ids, _to_res(ids, config.READING_PARENT_RES))
    slot = _slots(ids, config.READING_PARENT_RES, config.READING_RES)
    dest = block.astype(np.int64) * config.READING_SLOTS + slot

    # Which solver cell each base cell's minutes come from. Where the base cell
    # was not split it IS a solver cell; where graph/refine.py split it, the
    # value is its FINE_RES centre child's -- the same "what a pointer at this
    # spot means" rule tier A uses, so the two tiers cannot disagree about
    # which child speaks for a cell.
    source = np.full(len(idx.base_cells), -1, dtype=np.int64)
    whole = ~np.asarray(idx.fine, dtype=bool)
    source[idx.base_index[whole]] = np.flatnonzero(whole)
    for bpos in np.flatnonzero(source < 0):
        pos = idx.try_cell_index(
            h3.cell_to_center_child(idx.base_cells[bpos], config.FINE_RES))
        if pos is not None:
            source[bpos] = pos

    return ReadingLayout(
        parents=[h3.int_to_str(int(v)) for v in parent_ids], dest=dest, source=source)


def write_reading(idx, cell_minutes: np.ndarray, out: Path,
                  layout: ReadingLayout | None = None) -> None:
    """The res-`READING_RES` block array for one origin."""
    layout = layout or reading_layout(idx)
    values = np.full(len(layout.source), np.inf, dtype=np.float64)
    has = layout.source >= 0
    values[has] = cell_minutes[layout.source[has]]

    # Padding -- pentagon holes, and the res-6 cells inside a land-touching
    # res-3 parent that are not land -- keeps the fill rather than a time.
    blocks = np.full(layout.n_slots, config.UNREACHABLE, dtype="<u2")
    blocks[layout.dest] = _encode(values)
    _io.write_bytes(out, blocks.tobytes())


def write_reading_parents(idx, out: Path) -> None:
    """reading_parents.bin: the block ordering, once for the whole site."""
    ids = np.array([h3.str_to_int(c) for c in reading_parents(idx)], dtype="<u8")
    _io.write_bytes(out, ids.tobytes())
