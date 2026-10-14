#!/usr/bin/env python3
"""Ground-only minutes for named journeys, under the shipped road constants
and any alternative given on the command line.

    uv run python scripts/ground_pairs.py
    uv run python scripts/ground_pairs.py --config a:5,87,52,52,28,25:20:1.6:1.6 \\
                                          --config b:5,92,46,47,37,25:20:1.6:2.5

Each --config is name:class speeds (roadless..local):radius km:factor:highway
factor.

A check, not a fit: the pairs are the ones the 2026-10-14 audit flagged, with
Google's driving time where it measured one. Moving a constant to make these
come out right is exactly what calibration.toml's provenance rule forbids;
this prints what a FITTED change does to them. Builds the ground graph once
(~13 GB, ~15 min) and re-weights it per configuration.
"""

from __future__ import annotations

import argparse

import h3
import numpy as np
import scipy.sparse as sp

from transport_maps.graph import ground as gmodel
from transport_maps.graph import nodes, refine
from transport_maps.sources import countries, roads, urban

# (label, from lat/lon, to lat/lon, Google free-flow driving minutes or None)
PAIRS = [
    ("Minna -> ABV", 9.6139, 6.5569, 9.0068, 7.2632, None),
    ("Damietta -> PSD", 31.4165, 31.8133, 31.2794, 32.2400, None),
    ("Ondo -> Akure", 7.0932, 4.8353, 7.2526, 5.1931, None),
    ("Tawau -> TWU", 4.2448, 117.8912, 4.3133, 118.1219, None),
    ("Los Angeles -> San Diego", 34.0522, -118.2437, 32.7157, -117.1611, 118),
    ("Johannesburg -> Pretoria", -26.2041, 28.0473, -25.7479, 28.2293, None),
    ("Kuala Lumpur -> Malacca", 3.1390, 101.6869, 2.1896, 102.2501, None),
    ("Copenhagen -> Malmo", 55.6761, 12.5683, 55.6050, 13.0038, 47),
    ("Tokyo -> NRT", 35.6762, 139.6503, 35.7720, 140.3929, 72),
    ("London -> LHR", 51.5074, -0.1278, 51.4700, -0.4543, 45),
    ("Paris -> CDG", 48.8566, 2.3522, 49.0097, 2.5479, 44),
    ("New York -> JFK", 40.7128, -74.0060, 40.6413, -73.7781, 39),
    ("Bangkok -> BKK", 13.7563, 100.5018, 13.6900, 100.7501, 36),
    ("Zanzibar -> ZNZ", -6.1639, 39.1979, -6.2220, 39.2249, None),
    ("Beira -> BEW", -19.8436, 34.8389, -19.7964, 34.9076, None),
    ("Sochi -> AER", 43.5970, 39.7248, 43.4499, 39.9566, None),
    ("Chita -> HTA", 52.0431, 113.4917, 52.0263, 113.3056, None),
]


def config_of(args) -> list[tuple[str, np.ndarray, float, float, float]]:
    """(name, class speeds, congestion radius, factor, highway factor). The
    first two use the shipped constants, on GRIP4's raw footprint classes
    and on sources/roads.cell_class's filled ones."""
    shipped = (gmodel.SPEED_BY_ROAD_CLASS_KMH.copy(), urban.URBAN_RADIUS_KM,
               urban.URBAN_CONGESTION_FACTOR, urban.URBAN_CONGESTION_FACTOR)
    out = [("raw grip", *shipped), ("shipped", *shipped)]
    for spec in args.config or []:
        name, speeds, radius, factor, hw = spec.split(":")
        out.append((name, np.array([float(v) for v in speeds.split(",")]), float(radius),
                    float(factor), float(hw)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", action="append")
    args = ap.parse_args()
    import gc

    gc.disable()                     # as build-all does; see calibrate_ground.plan
    idx = nodes.build_index()
    classes = gmodel.cell_class(idx).astype(np.int64)
    base = idx.base_cells if len(getattr(idx, "base_cells", [])) else idx.cells
    raw = roads.footprint_class(base)[0]
    raw = (refine.expand(raw, idx) if len(getattr(idx, "base_cells", [])) else raw).astype(np.int64)
    country = countries.cell_country(idx.cells)
    zone = gmodel.cell_zones(country)
    centroids = np.array([h3.cell_to_latlng(x) for x in idx.cells])
    plat, plon = urban._places()
    near = np.full(len(centroids), np.inf)
    coslat = np.cos(np.radians(centroids[:, 0]))
    for la, lo in zip(plat, plon):
        d = np.hypot((centroids[:, 0] - la) * 111.0, (centroids[:, 1] - lo) * 111.0 * coslat)
        np.minimum(near, d, out=near)

    ends = []
    for label, la1, lo1, la2, lo2, google in PAIRS:
        s = idx.try_cell_index(idx.cell_at(la1, lo1))
        t = idx.try_cell_index(idx.cell_at(la2, lo2))
        ends.append((label, s, t, google))

    results = {}
    for name, speeds, radius, factor, hw_factor in config_of(args):
        cls = raw if name == "raw grip" else classes
        v = speeds[cls]
        congested = (near <= radius) & (cls > 0)
        f = np.where(cls == 1, hw_factor, factor)
        v = np.where(congested, v / f, v)
        r, c, d = gmodel.hex_edges(idx, speeds=v, country=country, zone=zone)
        csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
        for label, s, t, _g in ends:
            if s is None or t is None:
                results[(name, label)] = None
                continue
            results[(name, label)] = float(sp.csgraph.dijkstra(csr, indices=[s])[0][t])
        print(f"  {name}: speeds {speeds.tolist()} radius {radius} factor {factor} "
              f"highway factor {hw_factor}", flush=True)

    names = [c[0] for c in config_of(args)]
    print(f"\n  {'journey':28}" + "".join(f"{n:>10}" for n in names) + f"{'google':>9}")
    for label, s, t, google in ends:
        row = "".join(f"{results[(n, label)]:>10.0f}" if results[(n, label)] is not None
                      else f"{'-':>10}" for n in names)
        print(f"  {label:28}{row}{google if google else '':>9}")


if __name__ == "__main__":
    main()
