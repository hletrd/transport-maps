#!/usr/bin/env python3
"""Measure the ground model against known city-to-airport journey times.

Not a test: six hand-picked cities are far too thin to fit against, which is
exactly why the speed table is NOT tuned to them. This exists so the size of
the known error is a number anyone can reproduce in a minute, and so that
Task 13's Google Routes calibration has a target to beat.

    uv run python scripts/ground_check.py
"""

import h3
import numpy as np
import scipy.sparse as sp

from transport_maps import config
from transport_maps.graph import ground, nodes

# (label, city lat/lon, airport lat/lon, typical real door-to-terminal minutes)
CASES = [
    ("Seoul -> ICN", 37.5665, 126.9780, 37.4602, 126.4407, 65),
    ("Tokyo -> NRT", 35.6762, 139.6503, 35.7720, 140.3929, 80),
    ("London -> LHR", 51.5074, -0.1278, 51.4700, -0.4543, 50),
    ("Paris -> CDG", 48.8566, 2.3522, 49.0097, 2.5479, 50),
    ("New York -> JFK", 40.7128, -74.0060, 40.6413, -73.7781, 60),
    ("Bangkok -> BKK", 13.7563, 100.5018, 13.6900, 100.7501, 50),
]


def main() -> None:
    idx = nodes.build_index()
    r, c, d = ground.hex_edges(idx)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()

    print(f"  {'route':18}{'model':>8}{'real':>7}{'ratio':>8}")
    ratios = []
    for label, la1, lo1, la2, lo2, real in CASES:
        s = idx.try_cell_index(h3.latlng_to_cell(la1, lo1, config.SOLVE_RES))
        t = idx.try_cell_index(h3.latlng_to_cell(la2, lo2, config.SOLVE_RES))
        if s is None or t is None:
            print(f"  {label:18}   (no land cell)")
            continue
        m = sp.csgraph.dijkstra(csr, indices=[s])[0][t]
        ratios.append(real / m)
        print(f"  {label:18}{m:>8.1f}{real:>7}{real / m:>8.1f}x")
    print(f"\n  median: the model is {np.median(ratios):.1f}x too fast on urban access")


if __name__ == "__main__":
    main()
