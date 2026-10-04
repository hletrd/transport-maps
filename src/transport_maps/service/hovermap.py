"""The whole map from one point, on the page's own res-4 grid.

A charted city's map is two things the build writes: band tiles, and
`{slug}.bin`, the minutes per `hover_cells.bin` cell. `/api/map` answers the
second for an arbitrary point, and the page paints the first from it. So the
array this module produces must be `{slug}.bin`'s, entry for entry: the same
cells, in the same order, each valued by the same child, clipped to the same
sentinel. Anything else is a map that disagrees with the readout beside it.

The rule is `emit/hover.py`'s, and it is restated here rather than imported
because this package may not import `transport_maps.emit`
(`tests/service/test_wire.py`, the seam): each res-4 parent reports its
CENTRE child at SOLVE_RES, or the FINE_RES centre child where that base cell
was split, and its fastest child (ties to the lowest node position) only when
neither centre is land. `tests/service/test_hovermap.py` holds this module to
`emit.hover.write_hover` byte for byte on a fixture with split, missing and
tied children, so the restatement cannot drift from the original.

Everything that does not depend on the departure -- which parent each cell
belongs to, each parent's centre, and the cells of the parents that have none
-- is worked out ONCE, when the service starts, with numpy over the bundle's
13.8 million cell ids: no per-cell Python, no h3 call per cell. A request then
costs a gather over 90,740 centres and a grouped minimum over the fallback
cells.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from transport_maps import config

# The shipped uint16's ceiling, as emit/hover.py writes it: anything at or past
# 65,534 minutes (45 days) is the sentinel, never a duration.
MAX_MINUTES = config.UNREACHABLE - 1

# --- H3 bit layout, as emit/hover.py reads it --------------------------------
# Resolution in bits 52-55, fifteen 3-bit digits below it, digit r at bits
# (45-3r)..(47-3r), unused digits all ones. tests/service/test_hovermap.py pins
# both helpers against h3's own cell_to_parent and cell_to_center_child,
# pentagons included.
_RES_SHIFT = np.uint64(52)
_RES_MASK = np.uint64(0xF)
_MAX_RES = 15


def _digit_shift(res: int) -> np.uint64:
    return np.uint64(45 - 3 * res)


def to_res(ids: np.ndarray, res: int) -> np.ndarray:
    """h3's cell_to_parent, vectorised: coarsen cell ids to `res`."""
    out = (ids & ~(_RES_MASK << _RES_SHIFT)) | (np.uint64(res) << _RES_SHIFT)
    for r in range(res + 1, _MAX_RES + 1):
        out = out | (np.uint64(7) << _digit_shift(r))
    return out


def centre_child(ids: np.ndarray, parent_res: int, res: int) -> np.ndarray:
    """h3's cell_to_center_child, vectorised: digit 0 at every level from
    `parent_res + 1` to `res`. Digit 0 is the centre of a pentagon as well."""
    out = (ids & ~(_RES_MASK << _RES_SHIFT)) | (np.uint64(res) << _RES_SHIFT)
    for r in range(parent_res + 1, res + 1):
        out = out & ~(np.uint64(7) << _digit_shift(r))
    return out


def _positions(sorted_ids: np.ndarray, sorted_pos: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Node position of each id in `query`, or -1 where it is not a node."""
    i = np.searchsorted(sorted_ids, query)
    inside = i < len(sorted_ids)
    found = np.zeros(len(query), dtype=bool)
    found[inside] = sorted_ids[i[inside]] == query[inside]
    out = np.full(len(query), -1, dtype=np.int64)
    out[found] = sorted_pos[i[found]]
    return out


@dataclass(frozen=True)
class HoverIndex:
    """Which solver cell speaks for each res-4 hover cell, minus the part that
    depends on the departure.

    `parents` is hover_cells.bin's list -- the sorted res-4 parents of every
    solver cell, which is how `emit/hover.hover_cells` makes it. `centre` is
    each parent's centre cell's node position, or -1 where neither centre is
    land. For those parents only, `fallback` holds the positions of their
    cells, grouped by parent and ascending within a group; group k starts at
    `starts[k]` and belongs to parent `groups[k]`.
    """

    parents: np.ndarray      # (P,) uint64
    centre: np.ndarray       # (P,) int64
    fallback: np.ndarray     # (F,) int32
    starts: np.ndarray       # (G,) int64
    groups: np.ndarray       # (G,) int64

    @property
    def nbytes(self) -> int:
        return sum(a.nbytes for a in (self.parents, self.centre, self.fallback,
                                      self.starts, self.groups))


def build_index(cells: np.ndarray, sorted_ids: np.ndarray, sorted_pos: np.ndarray,
                *, hover_res: int = config.HOVER_RES, solve_res: int = config.SOLVE_RES,
                fine_res: int = config.FINE_RES) -> HoverIndex:
    """The HoverIndex of a bundle's cells (uint64 ids in node order), with the
    bundle's own sorted lookup."""
    cells = np.asarray(cells, dtype=np.uint64)
    parents, inverse = np.unique(to_res(cells, hover_res), return_inverse=True)
    inverse = inverse.reshape(-1)
    # emit/hover.hover_groups: the SOLVE_RES centre where it is a node, else
    # the FINE_RES centre where THAT is one.
    at_solve = _positions(sorted_ids, sorted_pos, centre_child(parents, hover_res, solve_res))
    at_fine = _positions(sorted_ids, sorted_pos, centre_child(parents, hover_res, fine_res))
    centre = np.where(at_solve >= 0, at_solve, at_fine)
    fallback = np.flatnonzero(centre[inverse] < 0)
    group_of = inverse[fallback]
    del inverse
    # Stable, so each group keeps ascending node positions: the tie rule
    # below takes the first minimum, which is then the lowest position, as
    # emit's lexsort on (position, minutes, parent) does.
    order = np.argsort(group_of, kind="stable")
    fallback, group_of = fallback[order], group_of[order]
    starts = np.flatnonzero(np.r_[True, group_of[1:] != group_of[:-1]]) if len(fallback) \
        else np.zeros(0, dtype=np.int64)
    return HoverIndex(parents=parents, centre=centre.astype(np.int64),
                      fallback=fallback.astype(np.int32), starts=starts.astype(np.int64),
                      groups=group_of[starts].astype(np.int64))


def check_order(index: HoverIndex, hover_cells: Path) -> None:
    """ValueError unless `hover_cells` (the page's hover_cells.bin) lists
    exactly the index's parents, in the same order. An array in any other
    order is a map of plausible times in the wrong places, with no error
    anywhere, so the service refuses to start rather than serve one."""
    shipped = np.fromfile(Path(hover_cells), dtype="<u8")
    if shipped.shape != index.parents.shape or not np.array_equal(shipped, index.parents):
        raise ValueError(
            f"{hover_cells} lists {len(shipped)} cells that are not the bundle's "
            f"{len(index.parents)} hover parents in the same order: the two come from "
            "different builds, and a map read through one by the other would put "
            "every time in the wrong place")


def representatives(index: HoverIndex, dist: np.ndarray) -> np.ndarray:
    """(P,) the node position that speaks for each hover cell in one solve:
    emit/hover.representative_array's answer, which is what lets a later
    array keyed on the same rule (an arrival airport, a mode breakdown) agree
    with this one. Among tied children it is the lowest position -- invisible
    in the minutes, which tie, and not in anything read through the cell."""
    rep = index.centre.copy()
    if len(index.fallback):
        v = np.asarray(dist[index.fallback], dtype=float)
        lowest = np.minimum.reduceat(v, index.starts)
        counts = np.diff(np.r_[index.starts, len(v)])
        # A solve's distances are finite or inf, never NaN, so every group
        # holds its own minimum at least once (inf == inf included).
        hit = np.flatnonzero(v == np.repeat(lowest, counts))
        group = np.searchsorted(index.starts, hit, side="right") - 1
        first = hit[np.r_[True, group[1:] != group[:-1]]]
        if len(first) != len(index.groups):
            raise ValueError("a fallback group has no minimum; the distances hold a NaN")
        rep[index.groups] = index.fallback[first]
    return rep


def map_minutes(index: HoverIndex, dist: np.ndarray) -> np.ndarray:
    """(P,) float minutes per hover cell from one solve's `dist`."""
    return np.asarray(dist[representatives(index, dist)], dtype=float)


def encode(minutes: np.ndarray) -> np.ndarray:
    """Minutes to the shipped little-endian uint16, sentinel included --
    emit/hover._encode exactly, which TRUNCATES a fractional minute rather than
    rounding it. A rounded copy would differ from a charted city's array by a
    minute in half its cells."""
    return np.where(np.isfinite(minutes) & (minutes < MAX_MINUTES), minutes,
                    config.UNREACHABLE).astype("<u2")
