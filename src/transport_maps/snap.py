"""The two-ring snap onto the nearest indexed land cell.

Its own module, with nothing but h3 and config, because two very different
processes need the SAME search: the build (airports in graph/nodes, origins in
solve/dijkstra) and the resident solver service, which must not import the
graph package (service/__init__.py says why). A copy in each would be free to
disagree with the other about where a point departs from.

`cell_pos` and `split` are anything supporting `in` and, for `cell_pos`,
`.get` -- the build passes a dict and a frozenset, the service its numpy-backed
lookups (service/bundle.py).
"""

import h3

from transport_maps import config


def _nearest_land(cell: str, cell_pos: dict[str, int], lat: float, lon: float,
                  split: frozenset | set = frozenset()) -> tuple[int, float] | None:
    """The nearest indexed cell within two rings of `cell`: (position, km), or None.

    Ring neighbours are looked up at `cell`'s own resolution. A neighbour that
    is absent from the index because it was SPLIT (it is present only as its
    FINE_RES children) contributes those children instead; a fine neighbour
    whose base cell was not split contributes that base cell. Without the
    split case every dense coastal cell -- exactly the land beside a
    reclaimed-island airport -- was invisible to the search: Kitakyushu was
    dropped with land 5 km away and Bodø was wired to a cell 11 km off past six
    adjacent land cells. Every candidate across both rings is compared by
    distance, so "nearest" means nearest and not first-found. Two rings reach
    about 13 km from a res-6 cell (the case that arises: an off-mask cell is
    never split) and about 5 km from a res-7 one.
    """
    best: tuple[int, float] | None = None
    for ring in (1, 2):
        for n in h3.grid_ring(cell, ring):
            if n in cell_pos:
                candidates = (n,)
            elif n in split:
                candidates = h3.cell_to_children(n, config.FINE_RES)
            elif h3.get_resolution(n) > config.SOLVE_RES:
                candidates = (h3.cell_to_parent(n, config.SOLVE_RES),)
            else:
                continue
            for candidate in candidates:
                pos = cell_pos.get(candidate)
                if pos is None:
                    continue
                km = h3.great_circle_distance((lat, lon), h3.cell_to_latlng(candidate), unit="km")
                if best is None or km < best[1]:
                    best = (pos, km)
    return best
