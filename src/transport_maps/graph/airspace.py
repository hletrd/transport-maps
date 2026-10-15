"""How much farther a flight goes when it may not cross closed airspace.

Ukraine's airspace has been closed to civil flights since 24 February 2022,
and Russia's (with Belarus's) to the airlines of the states it named in
February-March 2022 -- the EU, the UK, the US, Canada and others -- while
Japanese, Korean and Taiwanese airlines keep out of it by choice. A flight
whose great circle crosses closed airspace flies around it: Haneda-Paris was
12 h 11 on the great circle in the model against 14 h 30-14 h 40 scheduled
in 2026 (audit, 2026-10-14).

The detour is geometry, not a fitted constant. The globe is tiled with H3
cells at GRID_RES; a cell whose centre lies in closed airspace is removed, the
shortest path between two airports' cells round the rest is found, and that
corridor is pulled taut into great-circle legs that stay clear of the closed
area (`_pulled_km`). Block time then follows from the flown distance through
the fitted airborne model (calibration.toml [airborne]); nothing here is
tuned to a schedule. Checked against published 2026 block times (both
directions averaged, since the model has no wind): HEL-HKG (Finnair AY99/100,
11 h 48 / 13 h 40), ICN-FRA (13 h 20-14 h / 11 h 20-12 h), HEL-NRT (AY73,
13 h 20) and HND-CDG (14 h 30-14 h 40 westbound) -- see the commit that added
this module for the figures it produced.

Which airlines may cross Russia is the route data's own evidence
(sources/routes.py, `overfly`): an airline that serves an airport in Russia or
Belarus in the same crawl is not under the ban, plus the few documented
overfliers that serve neither (routes.OVERFLY_ALSO). A pair flown by any such
airline is solved on the great circle except across Ukraine.
"""

from __future__ import annotations

import h3
import numpy as np
import shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

#: Closed to every civil flight (ADM0_A3 codes, Natural Earth).
CLOSED_TO_ALL = ("UKR",)
#: Closed to the airlines that may not overfly Russia.
CLOSED_TO_RESTRICTED = ("RUS", "BLR")
#: H3 resolution of the routing grid: res 3 cells average 12,393 km^2 (about
#: 69 km edge to edge), fine enough to resolve a detour of a few hundred km
#: and coarse enough to route every affected pair in seconds.
GRID_RES = 3


class Grid:
    """The routing grid and its two closed sets, built once per process."""

    def __init__(self, geoms, codes) -> None:
        def union(which):
            parts = [g for g, c in zip(geoms, codes) if c in which]
            u = shapely.union_all(parts) if parts else shapely.Polygon()
            shapely.prepare(u)
            return u

        self.closed_all = union(CLOSED_TO_ALL)
        self.closed_restricted = union(CLOSED_TO_ALL + CLOSED_TO_RESTRICTED)
        cells = sorted(c for r in h3.get_res0_cells() for c in h3.cell_to_children(r, GRID_RES))
        self.cells = cells
        self.index = {c: i for i, c in enumerate(cells)}
        ll = np.array([h3.cell_to_latlng(c) for c in cells])
        self.latlng = ll
        rows, cols, w = [], [], []
        for i, c in enumerate(cells):
            for n in h3.grid_ring(c, 1):
                j = self.index[n]
                rows.append(i)
                cols.append(j)
                w.append(h3.great_circle_distance(tuple(ll[i]), tuple(ll[j]), unit="km"))
        self.rows, self.cols, self.w = np.array(rows), np.array(cols), np.array(w)
        self.graphs = {}
        for name, closed in (("all", self.closed_all), ("restricted", self.closed_restricted)):
            shut = shapely.contains_xy(closed, ll[:, 1], ll[:, 0])
            keep = ~(shut[self.rows] | shut[self.cols])
            n = len(cells)
            self.graphs[name] = (csr_matrix((self.w[keep], (self.rows[keep], self.cols[keep])),
                                            shape=(n, n)), shut)
        n = len(cells)
        self.free = csr_matrix((self.w, (self.rows, self.cols)), shape=(n, n))


def _crosses(closed, a, b, step_km: float = 25.0) -> bool:
    """Whether the great circle from a to b passes over `closed` between its
    ends (the ends themselves are not judged: an airport in closed airspace
    is served by airlines that may use it)."""
    pts = great_circle_points(a, b, step_km)
    return bool(shapely.contains_xy(closed, pts[1:-1, 1], pts[1:-1, 0]).any())


def great_circle_points(a, b, step_km: float = 25.0) -> np.ndarray:
    """(lat, lon) points every `step_km` along the great circle a -> b."""
    la1, lo1, la2, lo2 = np.radians([*a, *b])
    p1 = np.array([np.cos(la1) * np.cos(lo1), np.cos(la1) * np.sin(lo1), np.sin(la1)])
    p2 = np.array([np.cos(la2) * np.cos(lo2), np.cos(la2) * np.sin(lo2), np.sin(la2)])
    om = float(np.arccos(np.clip(p1 @ p2, -1.0, 1.0)))
    if om < 1e-9:
        return np.array([a, b], dtype=float)
    t = np.linspace(0.0, 1.0, max(2, int(om * 6371.0 / step_km) + 1))[:, None]
    v = (np.sin((1 - t) * om) * p1 + np.sin(t * om) * p2) / np.sin(om)
    return np.c_[np.degrees(np.arcsin(v[:, 2])), np.degrees(np.arctan2(v[:, 1], v[:, 0]))]


def _pulled_km(closed, points: np.ndarray) -> float:
    """Length of the path through `points` pulled taut round `closed`."""
    return _pulled(closed, points)[0]


def _pulled(closed, points: np.ndarray) -> tuple[float, list[int]]:
    """(length, the indices of `points` it turns at) of the path through
    `points` pulled taut round `closed`: from each point, straight on to the
    farthest later point whose great circle stays clear, found by bisection.
    Every segment kept is checked clear, so the result is a real path round
    the closed area; on the grid's own corridor it is within a few per cent of
    the shortest one. The turns are what the page draws the flight through."""
    total, i, n = 0.0, 0, len(points) - 1
    turns: list[int] = []
    while i < n:
        if not _crosses(closed, points[i], points[n]):
            j = n
        else:
            lo, hi = i + 1, n          # lo is clear (adjacent cells), hi is not
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if _crosses(closed, points[i], points[mid]):
                    hi = mid
                else:
                    lo = mid
            j = lo
        total += h3.great_circle_distance(tuple(points[i]), tuple(points[j]), unit="km")
        if j < n:
            turns.append(j)
        i = j
    return total, turns


def detoured_km(grid: Grid, pairs,
                paths_out: dict | None = None) -> dict[tuple[str, str], float]:
    """Flown distance for every pair whose great circle crosses the airspace
    closed to it. `pairs` holds (src, dst, (lat, lon), (lat, lon), overfly).
    Pairs that cross nothing are absent: they fly the great circle. A pair
    with an end in a closed cell, or no path around, is absent too -- the
    great circle is the honest fallback, not a guess.

    The grid's shortest path round the closed cells is only a corridor: its
    zig-zag along cell centres runs 0-10% over the great circle depending on
    the heading, so its length is not used. The path is pulled taut instead
    (`_pulled_km`), from airport to airport through the corridor's cells.

    Pass a dict as `paths_out` to receive, for each detoured pair, the points
    the taut path turns at between its two airports, (lat, lon) rounded to
    three decimals: the page draws the flight through them rather than on the
    great circle the timing no longer follows."""
    out: dict[tuple[str, str], float] = {}
    want: dict[str, list] = {"all": [], "restricted": []}
    for src, dst, a, b, overfly in pairs:
        name = "all" if overfly else "restricted"
        closed = grid.closed_all if overfly else grid.closed_restricted
        if _crosses(closed, a, b):
            want[name].append((src, dst, a, b))
    for name, items in want.items():
        if not items:
            continue
        g, shut = grid.graphs[name]
        closed = grid.closed_all if name == "all" else grid.closed_restricted
        cell = {}
        for src, dst, a, b in items:
            cell[src] = grid.index[h3.latlng_to_cell(*a, GRID_RES)]
            cell[dst] = grid.index[h3.latlng_to_cell(*b, GRID_RES)]
        sources = sorted({cell[s] for s, *_ in items})
        at = {c: k for k, c in enumerate(sources)}
        dist, pred = dijkstra(g, directed=True, indices=sources, return_predecessors=True)
        for src, dst, a, b in items:
            i, j = cell[src], cell[dst]
            if shut[i] or shut[j] or not np.isfinite(dist[at[i], j]):
                continue
            path = [j]
            while path[-1] != i:
                path.append(int(pred[at[i], path[-1]]))
            points = np.vstack([a, grid.latlng[path[::-1][1:-1]], b]) if len(path) > 2 \
                else np.array([a, b], dtype=float)
            gc = h3.great_circle_distance(a, b, unit="km")
            km, turns = _pulled(closed, points)
            out[(src, dst)] = max(gc, km)
            if paths_out is not None and km > gc:
                paths_out[(src, dst)] = [(round(float(points[t][0]), 3), round(float(points[t][1]), 3))
                                         for t in turns]
    return out
