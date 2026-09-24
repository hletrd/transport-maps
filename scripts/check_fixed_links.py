#!/usr/bin/env python3
"""Check the land-cell severing rule against named real crossings.

    uv run python scripts/check_fixed_links.py

Builds the real node index -- so the first run parses every region's fixed
links and polyfills the landmass ids, both then cached -- and asks, for each
case, whether the ground network joins the two points. Exits non-zero if any
case with an EXPECTED answer comes out the other way.

A case with `expect=None` is reported, not judged: it is here because its
answer was not known when the case was written, and guessing one would make
this script assert whatever the code happens to do.

The cases are named crossings, not component counts. An earlier check scored
the Seto Inland Sea against "one connected component" because that was what
the graph produced -- but that WAS the defect; most of its islands are
ferry-only, and the right number was never one.
"""

from __future__ import annotations

import dataclasses
import sys
from collections import deque

import h3

from transport_maps import config
from transport_maps.graph import nodes, refine

# (name, from (lat, lon), to (lat, lon), expected: True joined / False cut / None report)
CASES = [
    # Real fixed links that must stay joined.
    ("Great Seto Bridge  Kurashiki -> Takamatsu", (34.585, 133.772), (34.342, 134.047), True),
    ("Akashi-Kaikyo      Kobe -> Awaji",          (34.633, 135.022), (34.590, 135.017), True),
    ("Naruto Bridge      Awaji -> Shikoku",       (34.243, 134.654), (34.222, 134.644), True),
    ("Bosphorus          Europe -> Asia",         (41.030, 28.980), (41.020, 29.030), True),
    ("Kanmon             Honshu -> Kyushu",       (33.960, 130.960), (33.900, 130.900), True),
    # Geoje endpoint at Gohyeon, the island's town. The first one, (34.990,
    # 128.660), sat in a base cell straddling Geoje and Chilcheondo -- a
    # different island -- and once such cells were judged child by child the
    # point was on Chilcheondo's side of that strait.
    ("Geoga Bridge       Busan -> Geoje",         (35.080, 128.830), (34.885, 128.622), True),
    # Crossings only a ferry or an aircraft makes.
    ("Saipan -> Tinian   (the owner's report)",   (15.150, 145.730), (15.000, 145.630), False),
    ("Shodoshima         (ferry only)",           (34.490, 134.250), (34.330, 134.050), False),
    # Mainland control: nothing between them but land.
    ("control  Paris -> Brussels",                (48.857, 2.352), (50.850, 4.352), True),
    # Straits narrower than a cell, resolved child by child (graph/landmass
    # fine_cell_parts) -- joined only by ferry before; measured cut 2026-09-25.
    ("Messina strait     (ferry only)",           (38.190, 15.550), (38.110, 15.650), False),
    # Bridges whose span crosses a water cell (spanning_links, stitched across
    # ways and continued over islets the mask lacks) -- all three were cut
    # before; measured joined 2026-09-25. Oresund was joined before too, but
    # by the Helsingor narrows, not the bridge.
    ("Oresund Bridge     Copenhagen -> Malmo",    (55.676, 12.568), (55.605, 13.003), True),
    ("Great Belt         Zealand -> Funen",       (55.350, 11.100), (55.330, 10.800), True),
    ("Confederation Br.  PEI -> New Brunswick",   (46.230, -63.500), (46.100, -64.300), True),
]

# How far past the two endpoints the search may wander, in degrees. A land
# route that leaves this box is not found; every judged case is either an
# island or a short hop, so none of them needs one.
MARGIN_DEG = 1.5


def _joined(idx, a, b) -> bool | str:
    u = idx.try_cell_index(idx.cell_at(*a))
    v = idx.try_cell_index(idx.cell_at(*b))
    if u is None or v is None:
        return "endpoint off the land mask"
    lat0, lat1 = sorted((a[0], b[0]))
    lon0, lon1 = sorted((a[1], b[1]))

    def inside(pos):
        la, lo = h3.cell_to_latlng(idx.cells[pos])
        return (lat0 - MARGIN_DEG <= la <= lat1 + MARGIN_DEG
                and lon0 - MARGIN_DEG <= lo <= lon1 + MARGIN_DEG)

    # Spans are road bridges and tunnels joining cells that are NOT grid
    # neighbours (graph/landmass.spanning_links). Walking grid rings alone,
    # this search could never cross one, and reported the Great Belt cut
    # whatever the graph said.
    span_to: dict[int, list[int]] = {}
    for s_from, s_to in getattr(idx, "spans", {}) or {}:
        span_to.setdefault(s_from, []).append(s_to)

    seen, queue = {u}, deque([u])
    while queue:
        p = queue.popleft()
        if p == v:
            return True
        for q in span_to.get(p, ()):
            if q not in seen and inside(q):
                seen.add(q)
                queue.append(q)
        cell = idx.cells[p]
        for n in h3.grid_ring(cell, 1):
            q = idx.try_cell_index(n)
            if q is None and h3.get_resolution(cell) == config.FINE_RES:
                q = idx.try_cell_index(h3.cell_to_parent(n, config.SOLVE_RES))
            if q is None and h3.get_resolution(cell) == config.SOLVE_RES:
                for k in h3.cell_to_children(n, config.FINE_RES):
                    kq = idx.try_cell_index(k)
                    if kq is not None and kq not in seen and refine.ground_joined(idx, p, kq) \
                            and inside(kq):
                        seen.add(kq)
                        queue.append(kq)
                continue
            if q is not None and q not in seen and refine.ground_joined(idx, p, q) and inside(q):
                seen.add(q)
                queue.append(q)
    return False


def main() -> int:
    idx = nodes.build_index()
    if not idx.severed:
        print("!! the index severs nothing: fixed-link data is incomplete, so every case "
              "below would only report the old behaviour. Run scripts/osm_fixed_links.sh.")
        return 2
    print(f"  {len(idx.severed) // 2:,} adjacent cell pairs severed across open water\n")
    # The same index with nothing severed and no spans: the graph as it was. Without this
    # column a "cut" cannot say whether the rule made it or it always was --
    # the Great Belt looked like a regression until it was measured cut both ways.
    before = dataclasses.replace(idx, severed=frozenset(), spans={})
    print(f"  {'case':44} {'before':>8}  {'after':<28}")
    wrong = 0
    for name, a, b, expect in CASES:
        got = _joined(idx, a, b)
        was = _joined(before, a, b)
        shown = got if isinstance(got, str) else ("joined" if got else "cut")
        was_shown = was if isinstance(was, str) else ("joined" if was else "cut")
        if expect is None or isinstance(got, str):
            verdict = "report" if expect is None else "!! could not judge"
            wrong += isinstance(got, str) and expect is not None
        elif got == expect:
            verdict = "ok"
        else:
            verdict = f"!! WRONG, expected {'joined' if expect else 'cut'}"
            wrong += 1
        changed = "  (changed by the rule)" if was != got else ""
        print(f"  {name:44} {was_shown:>8}  {shown:28} {verdict}{changed}")
    print(f"\n  {wrong} case(s) wrong" if wrong else "\n  every judged case as expected")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
