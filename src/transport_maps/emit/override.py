"""Where the fine reading and the coarse route disagree, the route the fine cell took.

The page prints the res-6 reading under the pointer but builds the route panel
-- which airport, the legs, the surface modes -- from arrays kept per res-4
hover cell (itinerary.py, modes.py), taken from ONE representative child. A
res-4 cell is ~22 km across, and where two places inside it travel differently
the panel describes the wrong one. The owner's case: Saipan and Tinian share a
hover cell whose representative is on Saipan, so at Tinian the page printed the
right total, 9 h 34, over "Fly ICN -> SPN ... Onward from SPN ... by highway".

This ships, per origin, the res-6 cells whose own arrival airport differs from
their hover representative's: 283,096 of 4,091,715 from Seoul (6.9%), almost
all at the boundary between two airports' catchments, 1,454 where one flies and
the other does not. Each entry is the reading-tier slot, the airport and the
six mode totals -- 18 bytes, ~5 MB raw per origin.

Format, little-endian, three arrays back to back, sorted by slot so the page
binary-searches it: n uint32 slots, n uint16 airport ordinals (NO_AIRPORT for
none), n x len(CHANNELS) uint16 minutes. n = byteLength / ENTRY_BYTES.
"""

from pathlib import Path

import numpy as np

from transport_maps import _io
from transport_maps.graph.layout import layout_of

from .itinerary import NO_AIRPORT
from .modes import CHANNELS, MAX_MINUTES

ENTRY_BYTES = 4 + 2 + 2 * len(CHANNELS)
# Minutes on a train or a ferry above which a journey counts as using it, for
# telling a reading cell's route from its res-4 representative's. A few
# minutes is a station or a pier the path brushes; a quarter of an hour is a
# ride the legs should list.
MODE_DIFFERS_MIN = 15.0
# And when the totals part far enough that the representative's legs cannot be
# the journey printed above them: more than an hour, and more than half the
# longer of the two. Hong Kong -> Macau printed 2 h 40 over the res-4 cell's
# "42 min by highway" (2026-10-16). Measured on rebuild 33's arrays this adds
# about 50 slots an origin; the zone test below catches the rest of that case.
TIME_DIFFERS_MIN = 60.0
TIME_DIFFERS_SHARE = 0.5


def override_entries(idx, last: np.ndarray, acc: np.ndarray, rep: np.ndarray,
                     base_hover: np.ndarray, layout,
                     source: np.ndarray | None = None, *,
                     cell_minutes: np.ndarray | None = None,
                     zone: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(slots, airport ordinals, mode minutes) for the cells to override: those
    whose arrival airport differs from their res-4 representative's, that
    ride a train or a ferry the representative does not (or the reverse),
    that lie in another immigration zone than the representative (`zone`,
    per cell: the journey crosses a border the representative's does not), or
    whose total parts from the representative's by more than TIME_DIFFERS_MIN
    and TIME_DIFFERS_SHARE (`cell_minutes`).

    `last` is itinerary.arrival_airport_per_node, `acc` modes.mode_minutes_per_node,
    `rep` hover.representative_array (a node per hover parent), `base_hover` the
    hover parent of each base cell, `layout` hover.reading_layout, `source`
    hover.reading_source for this origin -- the node each reading slot
    shows, so the override describes the journey behind the very number
    printed there. Without it, `layout.source`.
    """
    src = layout.source if source is None else source
    rep_node = rep[base_hover]
    ok = (src >= 0) & (rep_node >= 0)
    own = np.where(ok, last[np.where(ok, src, 0)], -1)
    theirs = np.where(ok, last[np.where(ok, rep_node, 0)], -1)
    # A surface journey differs too when one of the two rides a train or a
    # ferry and the other does not: Hong Kong -> Macau read 1 h 57 by ferry
    # under legs listing 38 min by highway, the res-4 cell's bridge route
    # (2026-10-15). The airport test alone never saw it.
    special = [CHANNELS.index("rail"), CHANNELS.index("ferry")]
    mine = acc[np.where(ok, src, 0)][:, special] >= MODE_DIFFERS_MIN
    rep_modes = acc[np.where(ok, rep_node, 0)][:, special] >= MODE_DIFFERS_MIN
    differs = (own != theirs) | (mine != rep_modes).any(axis=1)
    if zone is not None:
        z = np.asarray(zone)
        za, zb = z[np.where(ok, src, 0)], z[np.where(ok, rep_node, 0)]
        differs |= (za != zb) & (za != "") & (zb != "")
    if cell_minutes is not None:
        ta = np.asarray(cell_minutes, dtype=np.float64)[np.where(ok, src, 0)]
        tb = np.asarray(cell_minutes, dtype=np.float64)[np.where(ok, rep_node, 0)]
        fin = np.isfinite(ta) & np.isfinite(tb)
        gap = np.abs(np.where(fin, ta - tb, 0.0))
        differs |= fin & (gap > TIME_DIFFERS_MIN) & (gap > TIME_DIFFERS_SHARE * np.maximum(ta, tb))
    pick = np.flatnonzero(ok & differs)
    slots = layout.dest[pick].astype(np.int64)
    order = np.argsort(slots, kind="stable")
    pick, slots = pick[order], slots[order]
    nodes = src[pick]
    # Either airport layer names the same airport (graph/layout.py).
    airport = np.where(last[nodes] >= 0, layout_of(idx).arrival_ordinal(last[nodes]), NO_AIRPORT)
    minutes = np.clip(np.nan_to_num(acc[nodes], posinf=0.0), 0, MAX_MINUTES)
    return slots, airport, minutes


def write_override(idx, last, acc, rep, base_hover, layout, out: Path,
                   source: np.ndarray | None = None, *,
                   cell_minutes: np.ndarray | None = None,
                   zone: np.ndarray | None = None) -> int:
    slots, airport, minutes = override_entries(idx, last, acc, rep, base_hover, layout, source,
                                               cell_minutes=cell_minutes, zone=zone)
    _io.write_bytes(out, slots.astype("<u4").tobytes() + airport.astype("<u2").tobytes()
                    + minutes.astype("<u2").tobytes())
    return len(slots)
