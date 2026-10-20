#!/usr/bin/env python3
"""Station-to-station train ride minutes, on the rides the graph is built from.

    uv run python scripts/rail_rides.py [--extracts DIR] [--pairs NAME,...]

The same rides `graph/build._rail_edges` turns into edges: OSM's relations
plus the timetables (`sources/gtfs_rail.with_timetables`), priced by
`graph/rail.ride_edges` and run both ways by `rail.two_way`. A journey boards
at a station in the origin's cell and alights in the destination's, as in the
graph; changing trains goes out to the cell and pays alighting and boarding
again, exactly as the graph charges it. Ground edges are left out, so a
change between two stations in different cells is not found -- the figure is
the train ride, the thing a timetable states, and it excludes the boarding
and alighting charges at the two ends.

Each PAIRS row names a check corridor by its two main stations' positions;
a journey may board at any station in the origin's solve cell.
"""

from __future__ import annotations

import argparse
import heapq
import logging
import pathlib
import resource
import sys
import time

import h3
import polars as pl

from transport_maps import config
from transport_maps.graph import rail
from transport_maps.sources import gtfs_rail, osm

# (name, from (lat, lon), to (lat, lon)): the main station of each end.
PAIRS = (
    ("Shin-Osaka -> Hiroshima", (34.7334, 135.5002), (34.3976, 132.4753)),
    ("Tokyo -> Shin-Osaka", (35.6812, 139.7671), (34.7334, 135.5002)),
    ("Tokyo -> Sendai", (35.6812, 139.7671), (38.2601, 140.8824)),
    ("Tokyo -> Kanazawa", (35.6812, 139.7671), (36.5781, 136.6481)),
    ("Hakata -> Kagoshima-Chuo", (33.5897, 130.4207), (31.5838, 130.5415)),
    ("Paris -> Lyon", (48.8443, 2.3744), (45.7606, 4.8594)),
    ("Paris -> Marseille", (48.8443, 2.3744), (43.3027, 5.3806)),
    ("Madrid -> Barcelona", (40.4065, -3.6895), (41.3791, 2.1400)),
    ("Zurich -> Geneva", (47.3779, 8.5403), (46.2102, 6.1425)),
    ("Vienna -> Salzburg", (48.1852, 16.3768), (47.8131, 13.0459)),
    ("Amsterdam -> Rotterdam", (52.3791, 4.9003), (51.9244, 4.4690)),
    ("Brussels -> Antwerp", (50.8355, 4.3360), (51.2172, 4.4211)),
    ("Rome -> Milan", (41.9010, 12.5011), (45.4863, 9.2042)),
    ("Oslo -> Bergen", (59.9110, 10.7528), (60.3903, 5.3328)),
    ("Helsinki -> Tampere", (60.1719, 24.9414), (61.4985, 23.7728)),
    ("Copenhagen -> Aarhus", (55.6726, 12.5649), (56.1500, 10.2047)),
    ("New York -> Washington", (40.7506, -73.9935), (38.8973, -77.0063)),
    ("Toronto -> Montreal", (43.6453, -79.3806), (45.5000, -73.5664)),
    ("Berlin -> Hamburg", (52.5251, 13.3694), (53.5530, 10.0067)),
    ("Seoul -> Busan", (37.5547, 126.9706), (35.1150, 129.0422)),
    ("London -> Paris", (51.5323, -0.1271), (48.8809, 2.3553)),
    ("London -> Brussels", (51.5323, -0.1271), (50.8355, 4.3357)),
    ("Beijing -> Shanghai", (39.8635, 116.3724), (31.1960, 121.3162)),
    ("Shanghai -> Hong Kong", (31.1960, 121.3162), (22.3037, 114.1649)),
    ("Xi'an -> Shanghai", (34.3777, 108.9340), (31.1960, 121.3162)),
    ("Beijing -> Fuzhou", (39.8635, 116.3724), (26.1168, 119.3156)),
    ("Changchun -> Shanghai", (43.8749, 125.1939), (31.1960, 121.3162)),
    ("Shanghai -> Kunming", (31.1960, 121.3162), (24.8734, 102.8604)),
    ("Taipei -> Zuoying", (25.0478, 121.5170), (22.6875, 120.3075)),
    ("New Delhi -> Mumbai", (28.6425, 77.2207), (18.9701, 72.8192)),
    ("New Delhi -> Varanasi", (28.6425, 77.2207), (25.3275, 82.9861)),
    ("New Delhi -> Howrah", (28.6425, 77.2207), (22.5836, 88.3423)),
    ("Stockholm -> Gothenburg", (59.3300, 18.0566), (57.7093, 11.9735)),
    ("Stockholm -> Malmo", (59.3300, 18.0566), (55.6098, 13.0008)),
    ("Warsaw -> Krakow", (52.2288, 21.0031), (50.0684, 19.9478)),
    ("Warsaw -> Gdansk", (52.2288, 21.0031), (54.3563, 18.6439)),
    ("Prague -> Brno", (50.0830, 14.4364), (49.1906, 16.6131)),
    ("Vienna -> Budapest", (48.1852, 16.3768), (47.5005, 19.0841)),
    ("Ankara -> Istanbul", (39.9349, 32.8434), (40.9907, 29.0380)),
    ("Tangier -> Casablanca", (35.7701, -5.7850), (33.5901, -7.5900)),
    ("Moscow -> St Petersburg", (55.7790, 37.6533), (59.9273, 30.3627)),
)


def rides(routes: pl.DataFrame, cal) -> pl.DataFrame:
    return rail.two_way(rail.ride_edges(routes, cal))


def measure(routes: pl.DataFrame, pairs=PAIRS) -> list[dict]:
    cal = rail.load_rail_calibration()
    edges = rides(routes, cal)
    st = rail.stations(routes)
    cell_of = dict(zip(st["station"], st["cell"], strict=True))
    name_of = dict(zip(st["station"], st["name"], strict=True))
    out: dict[str, list[tuple[str, float]]] = {}
    for a, b, m in zip(edges["from_station"], edges["to_station"], edges["minutes"], strict=True):
        out.setdefault(a, []).append((b, float(m)))
    in_cell: dict[str, list[str]] = {}
    for s, c in cell_of.items():
        in_cell.setdefault(c, []).append(s)

    def run(src_cell: str, dst_cell: str) -> tuple[float, list[str]]:
        # Nodes are stations and cells; cell -> station boards, station ->
        # cell alights, as graph/build._rail_edges builds them.
        dist = {("c", src_cell): 0.0}
        prev: dict = {}
        heap = [(0.0, ("c", src_cell))]
        while heap:
            d, node = heapq.heappop(heap)
            if d > dist.get(node, float("inf")):
                continue
            if node == ("c", dst_cell):
                path, n = [], node
                while n in prev:
                    if n[0] == "s":
                        path.append(n[1])
                    n = prev[n]
                return d - cal.boarding_min - cal.alighting_min, path[::-1]
            kind, key = node
            if kind == "c":
                nxt = [(("s", s), cal.boarding_min) for s in in_cell.get(key, ())]
            else:
                nxt = [(("s", t), m) for t, m in out.get(key, ())]
                nxt.append((("c", cell_of[key]), cal.alighting_min))
            for n, w in nxt:
                nd = d + w
                if nd < dist.get(n, float("inf")):
                    dist[n] = nd
                    prev[n] = node
                    heapq.heappush(heap, (nd, n))
        return float("nan"), []

    results = []
    for name, a, b in pairs:
        ca = h3.latlng_to_cell(*a, config.SOLVE_RES)
        cb = h3.latlng_to_cell(*b, config.SOLVE_RES)
        minutes, path = run(ca, cb)
        calls = [name_of.get(s, s) for s in path]
        results.append({"pair": name, "minutes": round(minutes, 1),
                        "changes": sum(s.endswith(rail.ALIGHT_SUFFIX) for s in path[:-1]),
                        "via": " > ".join(dict.fromkeys(c for c in calls if c))[:160]})
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--extracts", type=pathlib.Path, default=None,
                    help="directory of *-rail.osm.pbf (default data/cache/osm)")
    ap.add_argument("--no-timetables", action="store_true",
                    help="OSM's relations alone, no feed")
    ap.add_argument("--pairs", default="", help="comma-separated PAIRS names to run")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    t0 = time.monotonic()
    routes = osm.rail_routes(extracts_dir=args.extracts)
    if not args.no_timetables:
        routes = gtfs_rail.with_timetables(routes)
    t1 = time.monotonic()
    want = {p.strip() for p in args.pairs.split(",") if p.strip()}
    pairs = [p for p in PAIRS if not want or p[0] in want]
    for r in measure(routes, pairs):
        print(f"{r['pair']:26s} {r['minutes']:7.1f} min  changes {r['changes']}  {r['via']}")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / 2**20 if sys.platform == "darwin" else peak / 2**10
    print(f"routes and timetables {t1 - t0:.0f} s, rides {time.monotonic() - t1:.0f} s, "
          f"peak RSS {peak_mb:,.0f} MB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
