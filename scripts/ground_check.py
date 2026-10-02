#!/usr/bin/env python3
"""Measure the ground model against known city-to-airport journey times.

Superseded as a calibration input by scripts/calibrate_ground.py, which samples
real journeys from Google Routes instead of six hand-picked ones. It has run
twice: a first pass of 1,383 journeys (data/build/ground_samples.json) fitted
the urban factor, and a second of 2,998 (ground_samples2.json) fitted the
per-class speeds -- both recorded in calibration.toml ([urban], [ground]).
The first pass showed these six were not merely thin but misleading: they
implied the model was 2.1x too fast everywhere, when between towns it was only
1.12x out and the error was almost entirely urban.

Kept as a quick reproducible spot-check.

    uv run python scripts/ground_check.py
"""

import numpy as np
import scipy.sparse as sp

from transport_maps.graph import ground, nodes

# (label, city lat/lon, airport lat/lon, MEASURED driving minutes)
#
# These were hand-estimated once and the estimates were pessimistic -- they put
# JFK at 60 minutes where Google measures 39 -- which inflated the reported
# error. They are now the figures Google Routes actually returned. Seoul is
# absent because Google returns no driving route anywhere in South Korea.
CASES = [
    ("Tokyo -> NRT", 35.6762, 139.6503, 35.7720, 140.3929, 72),
    ("London -> LHR", 51.5074, -0.1278, 51.4700, -0.4543, 45),
    ("Paris -> CDG", 48.8566, 2.3522, 49.0097, 2.5479, 44),
    ("New York -> JFK", 40.7128, -74.0060, 40.6413, -73.7781, 39),
    ("Bangkok -> BKK", 13.7563, 100.5018, 13.6900, 100.7501, 36),
]


def main() -> None:
    idx = nodes.build_index()
    r, c, d = ground.hex_edges(idx)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()

    print(f"  {'route':18}{'model':>8}{'real':>7}{'ratio':>8}")
    ratios = []
    for label, la1, lo1, la2, lo2, real in CASES:
        s = idx.try_cell_index(idx.cell_at(la1, lo1))
        t = idx.try_cell_index(idx.cell_at(la2, lo2))
        if s is None or t is None:
            print(f"  {label:18}   (no land cell)")
            continue
        m = sp.csgraph.dijkstra(csr, indices=[s])[0][t]
        # `inf` when the two cells sit in different components -- a land-mask
        # regression, or an airport cut off from its city. `real / inf` is 0.0,
        # which silently dragged the median toward zero and read as "the model
        # is 0.0x too fast", the most reassuring possible output for the worst
        # possible input.
        if not np.isfinite(m) or m <= 0:
            print(f"  {label:18}   (no route: the two cells are not connected)")
            continue
        ratios.append(real / m)
        print(f"  {label:18}{m:>8.1f}{real:>7}{real / m:>8.1f}x")
    # np.median([]) is nan with a RuntimeWarning, which this printed as
    # "the model is nanx too fast" if every case had been skipped.
    if not ratios:
        print("\n  no case produced a route; nothing to compare.")
        return
    print(f"\n  median over {len(ratios)} of {len(CASES)} cases: the model is "
          f"{np.median(ratios):.1f}x too fast on urban access")


if __name__ == "__main__":
    main()
