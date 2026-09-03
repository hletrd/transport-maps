"""Pipeline entry point."""

import argparse
import re

from transport_maps import config
from transport_maps.contour import bands
from transport_maps.emit import hover, index, routes_json, tiles
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

    solve = sub.add_parser(
        "solve", help="solve one origin and write its PMTiles bands, hover array and routes"
    )
    solve.add_argument("--lat", type=float, required=True)
    solve.add_argument("--lon", type=float, required=True)
    solve.add_argument(
        "--name", required=True, type=_slug, help="origin slug, used for the filename"
    )

    sub.add_parser(
        "index", help="write index.json and the shared hover-cell ordering from origins.toml"
    )

    args = parser.parse_args()
    config.ensure_dirs()

    if args.command == "solve":
        idx = nodes.build_index()
        csr = build.build_graph(idx)
        source = dijkstra.origin_node(idx, args.lat, args.lon)
        minutes, predecessors = dijkstra.solve_from(csr, source, with_predecessors=True)

        fc = bands.band_feature_collection(idx, minutes[: idx.n_cells])
        pmtiles_out = config.DIST / f"{args.name}.pmtiles"
        tiles.write_pmtiles(fc, pmtiles_out)

        hover_out = config.DIST / f"{args.name}.hover.bin"
        hover.write_hover(idx, minutes[: idx.n_cells], hover_out)

        routes_out = config.DIST / f"{args.name}.routes.json"
        routes_json.write_routes(idx, minutes, predecessors, routes_out)

        print(f"wrote {pmtiles_out}, {hover_out}, {routes_out} ({len(fc['features'])} bands)")

    elif args.command == "index":
        origins = index.load_origins()
        idx = nodes.build_index()

        index_out = config.DIST / "index.json"
        index.write_index(origins, index_out)

        hover_cells_out = config.DIST / "hover_cells.bin"
        index.write_hover_cells(idx, hover_cells_out)

        print(f"wrote {index_out} ({len(origins)} origins), {hover_cells_out}")
