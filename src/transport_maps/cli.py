"""Pipeline entry point."""

import argparse
import re

from transport_maps import config, validate
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


def _build_all(limit: int | None = None) -> None:
    """Build the graph once, then solve, validate and emit every origin.

    Aborts on the first failing gate -- a partially written dist/ is worse
    than none. `limit` restricts to the first N origins, for smoke-testing.
    """
    idx = nodes.build_index()
    csr = build.build_graph(idx)
    # Graph-level gate: runs once, before any origin is solved, because a
    # disconnected airport is a property of the network rather than of a
    # particular origin -- and per-origin coverage cannot see it.
    validate.check_airport_connectivity(idx, csr)

    origins = index.load_origins()
    if limit is not None:
        origins = origins[:limit]

    # hover_cells.bin depends only on the graph, not on any origin, so it is
    # safe to write eagerly. index.json is different: it lists the origins the
    # frontend expects to find files for, so it must wait until every origin
    # below has actually succeeded -- writing it first would leave it naming
    # origins whose per-origin files an aborted run never produced.
    index.write_hover_cells(idx, config.DIST / "hover_cells.bin")

    print(f"{'origin':<20}{'coverage':>10}{'bands':>8}{'pmtiles KB':>12}")
    for origin in origins:
        slug = origin["slug"]
        source = dijkstra.origin_node(idx, origin["lat"], origin["lon"])
        minutes, predecessors = dijkstra.solve_from(csr, source, with_predecessors=True)

        coverage = validate.check_coverage(minutes, idx)
        if coverage < validate.MIN_COVERAGE:
            raise SystemExit(
                f"{slug}: coverage {coverage:.1%} below {validate.MIN_COVERAGE:.0%}"
            )
        validate.check_monotonic_ground(idx, minutes)

        fc = bands.band_feature_collection(idx, minutes[: idx.n_cells])
        validate.check_bands_disjoint(fc)

        out = config.DIST / "origins"
        tiles.write_pmtiles(fc, out / f"{slug}.pmtiles")
        hover.write_hover(idx, minutes[: idx.n_cells], out / f"{slug}.bin")
        routes_json.write_routes(idx, minutes, predecessors, out / f"{slug}.json")

        size_kb = (out / f"{slug}.pmtiles").stat().st_size // 1024
        print(f"{slug:<20}{coverage:>9.1%}{len(fc['features']):>8}{size_kb:>12}")

    # Only reached once every origin above has succeeded.
    index.write_index(origins, config.DIST / "index.json")


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

    build_all = sub.add_parser(
        "build-all", help="build the graph once and solve, validate and emit every origin"
    )
    build_all.add_argument(
        "--limit",
        type=int,
        default=None,
        help="only build the first N origins from origins.toml (for smoke-testing)",
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

    elif args.command == "build-all":
        _build_all(limit=args.limit)
