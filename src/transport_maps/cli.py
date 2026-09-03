"""Pipeline entry point."""

import argparse

from transport_maps import config
from transport_maps.contour import bands
from transport_maps.emit import geojson
from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra


def main() -> None:
    parser = argparse.ArgumentParser(prog="transport-maps")
    sub = parser.add_subparsers(dest="command", required=True)

    solve = sub.add_parser("solve", help="solve one origin and write band GeoJSON")
    solve.add_argument("--lat", type=float, required=True)
    solve.add_argument("--lon", type=float, required=True)
    solve.add_argument("--name", required=True, help="origin slug, used for the filename")

    args = parser.parse_args()
    if args.command == "solve":
        idx = nodes.build_index()
        csr = build.build_graph(idx)
        source = dijkstra.origin_node(idx, args.lat, args.lon)
        minutes = dijkstra.solve_from(csr, source)
        fc = bands.band_feature_collection(idx, minutes[: idx.n_cells])
        out = config.DIST / f"{args.name}.bands.geojson"
        geojson.write_bands(out, fc)
        print(f"wrote {out} with {len(fc['features'])} bands")
