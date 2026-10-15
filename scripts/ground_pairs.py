#!/usr/bin/env python3
"""Ground-only minutes for named journeys, under the shipped road model and
any fitted alternative.

    uv run python scripts/ground_pairs.py
    uv run python scripts/ground_pairs.py --fit data/build/ground_fit4.json

Each --fit is the JSON `calibrate_ground.py fit --out` writes: class speeds,
income multipliers, a time factor per class and city-scaled distance band,
and the minutes every journey pays at its two ends. Those end minutes are in
every figure printed, as the map charges them (service/bundle.
with_end_minutes); for an airport, half of them sit on its access edge.

A check, not a fit: the pairs are the ones the 2026-10-14 audit and its
rebuild-30 re-measure flagged, with Google's typical-traffic (Tuesday 10:00
local) and free-flow driving minutes from one TRAFFIC_AWARE call each
(2026-10-15). Moving a constant to make these come out right is exactly what
calibration.toml's provenance rule forbids; this prints what a FITTED change
does to them. Builds the ground graph once (~13 GB, ~15 min) and re-weights
it per configuration.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import scipy.sparse as sp

from transport_maps.calibrate import ground as gfit
from transport_maps.graph import ground as gmodel
from transport_maps.graph import nodes, refine
from transport_maps.sources import countries, urban

# (label, from lat/lon, to lat/lon, Google typical-traffic min, free-flow min)
PAIRS = [
    ("Mumbai -> Pune", 19.0760, 72.8777, 18.5204, 73.8567, 161, 159),
    ("Mexico City -> Puebla", 19.4326, -99.1332, 19.0414, -98.2063, 142, 134),
    ("Lagos -> Ibadan", 6.5244, 3.3792, 7.3775, 3.9470, 129, 124),
    ("Buenos Aires -> La Plata", -34.6037, -58.3816, -34.9205, -57.9536, 59, 58),
    ("Johannesburg -> Pretoria", -26.2041, 28.0473, -25.7479, 28.2293, 54, 53),
    ("Bangkok -> Pattaya", 13.7563, 100.5018, 12.9236, 100.8825, 125, 116),
    ("Los Angeles -> San Diego", 34.0522, -118.2437, 32.7157, -117.1611, 123, 118),
    ("Chicago -> Milwaukee", 41.8781, -87.6298, 43.0389, -87.9065, 93, 90),
    ("Kuala Lumpur -> Malacca", 3.1390, 101.6869, 2.1896, 102.2501, 122, 116),
    ("Cairo -> Alexandria", 30.0444, 31.2357, 31.2001, 29.9187, 151, 150),
    ("Delhi -> Agra", 28.6139, 77.2090, 27.1767, 78.0081, 204, 206),
    ("London -> LHR", 51.5074, -0.1278, 51.4700, -0.4543, 51, 45),
    ("Paris -> CDG", 48.8566, 2.3522, 49.0097, 2.5479, 48, 39),
    ("New York -> JFK", 40.7128, -74.0060, 40.6413, -73.7781, 48, 39),
    ("Tokyo -> NRT", 35.6762, 139.6503, 35.7720, 140.3929, 84, 74),
    ("Bangkok -> BKK", 13.7563, 100.5018, 13.6900, 100.7501, 42, 36),
    ("Minna -> ABV", 9.6139, 6.5569, 9.0068, 7.2632, None, None),
    ("Damietta -> PSD", 31.4165, 31.8133, 31.2794, 32.2400, None, None),
    ("Tawau -> TWU", 4.2448, 117.8912, 4.3133, 118.1219, None, None),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fit", action="append", default=[])
    ap.add_argument("--decompose", action="store_true",
                    help="break each shipped path down by class, built-up and road density")
    ap.add_argument("--rule", default=None,
                    help="motorway rule for the class map (sources/motorways.RULES); RULE if omitted")
    args = ap.parse_args()
    import gc

    gc.disable()                     # as build-all does; see calibrate_ground.plan
    idx = nodes.build_index()

    grip = gmodel.grip_class(idx).astype(np.int64)
    classes = gmodel.cell_class(idx, args.rule).astype(np.int64)
    raised = int(((grip != classes) & (classes == gmodel.TRUNK_FLOOR_CLASS)).sum())
    print(f"  trunk floor: {raised:,} of {len(classes):,} cells raised to class "
          f"{gmodel.TRUNK_FLOOR_CLASS}", flush=True)
    country = countries.cell_country(idx.cells)
    income = countries.cell_income_group(country)
    zone = gmodel.cell_zones(country)
    base = idx.base_cells if len(getattr(idx, "base_cells", [])) else idx.cells
    scaled, _pop = urban.scaled_city_distance(list(base))
    if len(getattr(idx, "base_cells", [])):
        scaled = refine.expand(scaled, idx)
    band = gfit.scaled_band_of(scaled)

    # (name, per-cell speed, minutes every journey pays at its two ends)
    configs = [("shipped", gmodel.cell_speed_kmh(idx, classes, country=country),
                gmodel.END_MINUTES)]
    for path in args.fit:
        f = json.loads(open(path).read())
        # A fit from before the motorway class is priced on GRIP4's classes
        # alone, exactly as its model was.
        own = classes if len(f["speeds"]) > gmodel.MOTORWAY_CLASS else grip
        v = gfit.cell_speeds_from_fit(f, own, income, band)
        configs.append((path.rsplit("/", 1)[-1].removesuffix(".json"), v, float(f.get("end_min", 0))))

    ends = [(label, idx.try_cell_index(idx.cell_at(a, b)), idx.try_cell_index(idx.cell_at(c, d)),
             traffic, free) for label, a, b, c, d, traffic, free in PAIRS]
    results = {}
    for name, v, end_min in configs:
        r, c, d = gmodel.hex_edges(idx, speeds=v, country=country, zone=zone)
        csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
        for label, s, t, _tr, _ff in ends:
            results[(name, label)] = (None if s is None or t is None
                                      else float(sp.csgraph.dijkstra(csr, indices=[s])[0][t])
                                      + end_min)
        print(f"  {name} done", flush=True)

    if args.decompose:
        _decompose(idx, configs[0][1], country, zone, classes, scaled, ends)
    names = [c[0] for c in configs]
    print(f"\n  {'journey':28}" + "".join(f"{n[:12]:>13}" for n in names) + f"{'traffic':>9}{'free':>6}")
    for label, _s, _t, traffic, free in ends:
        row = "".join(f"{results[(n, label)]:>13.0f}" if results[(n, label)] is not None
                      else f"{'-':>13}" for n in names)
        print(f"  {label:28}{row}{traffic or '':>9}{free or '':>6}")


def _decompose(idx, v, country, zone, classes, scaled, ends) -> None:
    """Per pair under the shipped speeds: km and minutes by road class, how
    much of each lies inside a city's built-up radius, the median road
    density, and the run of classes for short paths."""
    import h3

    from transport_maps.sources import roads

    r, c, d = gmodel.hex_edges(idx, speeds=v, country=country, zone=zone)
    csr = sp.coo_matrix((d, (r, c)), shape=(idx.n, idx.n)).tocsr()
    for label, s, t, traffic, _free in ends:
        if s is None or t is None:
            continue
        dist, pred = sp.csgraph.dijkstra(csr, indices=[s], return_predecessors=True)
        path, k = [t], t
        while k != s and pred[0][k] >= 0:
            k = int(pred[0][k])
            path.append(k)
        path = np.array(path[::-1])
        cent = np.array([h3.cell_to_latlng(idx.cells[i]) for i in path])
        seg = np.r_[0.0, gmodel.haversine_km(cent[:-1], cent[1:])]
        dens = roads.cell_road_density([idx.cells[i] for i in path])
        mins = seg / v[path] * 60.0
        print(f"\n  {label}: {seg.sum():.1f} km, {mins.sum():.0f} min on the path "
              f"(Google typical {traffic}), {len(path)} cells")
        for cl in np.unique(classes[path]):
            m = classes[path] == cl
            inb = m & (scaled[path] < 1.0)
            print(f"    class {cl}: {seg[m].sum():6.1f} km {mins[m].sum():6.1f} min "
                  f"({seg[m].sum() / max(mins[m].sum(), 1e-9) * 60:5.1f} km/h); "
                  f"inside built-up {seg[inb].sum():5.1f} km; "
                  f"median density {np.median(dens[m]):7.0f} m/km2")
        if len(path) <= 40:
            runs, prev = [], None
            for cl in classes[path]:
                if cl == prev:
                    runs[-1][1] += 1
                else:
                    runs.append([int(cl), 1])
                prev = cl
            print("    classes along the path: " + " ".join(f"{a}x{b}" for a, b in runs))


if __name__ == "__main__":
    main()
