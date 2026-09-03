"""Pipeline entry point."""

import argparse
import re

from transport_maps import config
from transport_maps.contour import bands
from transport_maps.emit import geojson
from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra

# Origin slugs become filenames under config.DIST, so reject anything that
# could escape that directory (path separators, "..", leading dots/dashes).
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _slug(name: str) -> str:
    if not _SLUG_RE.fullmatch(name):
        raise argparse.ArgumentTypeError(
            f"invalid --name {name!r}: must contain only letters, digits, '-' and '_'"
        )
    return name


def main() -> None:
    parser = argparse.ArgumentParser(prog="transport-maps")
    sub = parser.add_subparsers(dest="command", required=True)

    solve = sub.add_parser("solve", help="solve one origin and write band GeoJSON")
    solve.add_argument("--lat", type=float, required=True)
    solve.add_argument("--lon", type=float, required=True)
    solve.add_argument(
        "--name", required=True, type=_slug, help="origin slug, used for the filename"
    )

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
