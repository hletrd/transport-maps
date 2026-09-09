"""Pipeline entry point."""

import os

# Must precede every import that pulls in polars. Its rayon thread pool does
# not survive fork(): a child that touches polars blocks on the pool's lock
# forever. Eight workers sat at 0% CPU for 37 minutes before this was found.
# The parquet reads here are small; single-threaded costs nothing measurable.
os.environ.setdefault("POLARS_MAX_THREADS", "1")

import argparse
import logging
import multiprocessing
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from transport_maps import config, validate
from transport_maps.contour import bands, grid
from transport_maps.emit import (
    hover,
    index,
    itinerary,
    modes,
    rail_detail,
    routes_json,
    tiles,
)
from transport_maps.graph import build, ground, nodes, transfers
from transport_maps.solve import dijkstra
from transport_maps.sources import countries, osm

# Origin slugs become filenames under config.DIST, so reject anything that
# could escape that directory (path separators, "..", leading dots/dashes).
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _slug(name: str) -> str:
    if not _SLUG_RE.fullmatch(name):
        raise argparse.ArgumentTypeError(
            f"invalid --name {name!r}: must contain only letters, digits, '-' and '_'"
        )
    return name


def _load_rail():
    """Rail routes if the OSM extracts are present, else None.

    Absence is reported rather than assumed: a build that quietly drops rail
    looks identical to one that included it, and the difference is hours of
    travel time across Europe and Japan.
    """
    try:
        routes = osm.rail_routes()
    except FileNotFoundError as exc:
        print(f"rail:     EXCLUDED -- {exc}")
        return None
    print(f"rail:     included -- {routes['route_id'].n_unique():,} routes, "
          f"{len(routes):,} stops")
    return routes


def _worker_count(n_origins: int) -> int:
    """Workers to fork. Bounded by RAM, not by cores.

    Each fork shares the graph copy-on-write, but Python's refcounting touches
    object headers and gradually un-shares pages, so more workers cost more
    real memory than the arrays suggest.
    """
    # A handful of origins is not worth a fork -- and the test stubs record
    # their writes into a list that a forked child cannot append to in the
    # parent, which is how a two-origin test silently saw zero files written.
    if n_origins < 4:
        return 1
    cores = os.cpu_count() or 1
    return max(1, min(cores - 2, 8, n_origins))


def _worker_cap(n_cells: int) -> int:
    """Fewer forks for a big grid. Each worker's refcount traffic copies the
    cell-list pages it touches, and its own arrays scale with the graph; at
    ten million cells eight workers exceed 32 GB."""
    return 5 if n_cells > 3_000_000 else 8


# How long the parent waits on the next origin before checking that every
# worker is still the one it started. A worker killed by a signal (memory
# pressure, a native segfault, kill -9) never reports; multiprocessing.Pool
# quietly respawns it and imap blocks forever (CPython gh-66587, the fix
# closed unmerged in 2026), so the parent must notice on its own.
WORKER_POLL_S = 60.0
LOCK_NAME = ".build.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_lock(dist: Path) -> Path:
    """dist/.build.lock, created O_EXCL: one build per dist/ at a time.

    Nothing else prevented a second build-all, the water build or the deploy
    script's `rsync web/ dist/` from writing into a directory a build was
    rewriting in place. A stale lock (its pid gone) is reported, not reused:
    the owner removes it after checking what died.
    """
    dist.mkdir(parents=True, exist_ok=True)
    lock = dist / LOCK_NAME
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        pid, started = None, "?"
        try:
            parts = lock.read_text().split()
            pid, started = int(parts[0]), (parts[1] if len(parts) > 1 else "?")
        except (OSError, ValueError, IndexError):
            pass
        if pid is not None and _pid_alive(pid):
            raise SystemExit(f"{lock} is held by a running build (pid {pid}, started {started}); "
                             "wait for it to finish") from None
        raise SystemExit(f"{lock} is STALE: pid {pid} (started {started}) is gone; check what "
                         "died, then remove the lock file to build again") from None
    with os.fdopen(fd, "w") as fh:
        fh.write(f"{os.getpid()} {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}\n")
    return lock


def _other_builds() -> list[int]:
    """Pids of other build-all processes on this machine, from ps."""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    mine = os.getpid()
    found = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if "build-all" in cmd and ("transport_maps" in cmd or "transport-maps" in cmd):
            if pid.isdigit() and int(pid) != mine:
                found.append(int(pid))
    return found


def _watch_parent(parent_pid: int) -> None:
    """Pool initializer: a worker whose parent has died exits instead of
    living on under launchd. Eight idle workers from a killed build sat for
    ten hours before this existed; macOS has no PR_SET_PDEATHSIG."""
    def watch():
        while True:
            time.sleep(1.0)
            if os.getppid() != parent_pid:
                os._exit(1)
    threading.Thread(target=watch, daemon=True).start()


class GateFailure(RuntimeError):
    """A per-origin publication gate failed; the run must abort.

    A plain Exception on purpose. This used to be a SystemExit raised inside
    `_solve_one`, which is fine in the serial path and fatal in the forked
    one: multiprocessing.pool.worker catches only Exception, so the SystemExit
    killed the worker, the pool quietly respawned a replacement, the task's
    result never arrived and `imap` blocked forever -- a 553-origin build
    sitting at 0% CPU with no exit code and no traceback. A RuntimeError is
    pickled back to the parent, which terminates the pool and exits.
    """


def _solve_one(origin: dict, idx, csr, speeds, shared: dict) -> str:
    """Solve and emit one origin. Returns the table row to print."""
    slug = origin["slug"]
    source = dijkstra.origin_node(idx, origin["lat"], origin["lon"])
    minutes, predecessors = dijkstra.solve_from(csr, source, with_predecessors=True)

    coverage = validate.check_coverage(minutes, idx)
    if coverage < validate.MIN_COVERAGE:
        raise GateFailure(
            f"{slug}: coverage {coverage:.1%} below {validate.MIN_COVERAGE:.0%}"
        )
    validate.check_monotonic_ground(idx, minutes, speeds,
                                    country=shared["country"], zone=shared["zone"])

    fc = bands.band_feature_collection(idx, minutes[: idx.n_cells],
                                       grid=shared["grid"], native=shared["native"])
    validate.check_bands_cover(idx, shared["grid"], shared["native"], fc)

    out = config.DIST / "origins"
    tiles.write_pmtiles(fc, out / f"{slug}.pmtiles", workers=shared.get("workers"))
    hover.write_hover(idx, minutes[: idx.n_cells], out / f"{slug}.bin")
    routes_json.write_routes(idx, minutes, predecessors, out / f"{slug}.json")
    itinerary.write_itinerary(idx, minutes, predecessors, out / f"{slug}.air.bin")
    modes.write_modes(idx, minutes, predecessors, out / f"{slug}.modes.bin",
                      cell_class=shared["cell_class"])
    rail_detail.write_rail_detail(idx, minutes, predecessors, shared.get("rail_tables"),
                                  out / f"{slug}.rail.bin", out / f"{slug}.rail.json")

    size_kb = (out / f"{slug}.pmtiles").stat().st_size // 1024
    return f"{slug:<20}{coverage:>9.1%}{len(fc['features']):>8}{size_kb:>12}"


def _solve_one_forked(origin: dict) -> str:
    """Pool entry point. Reads the graph the fork inherited."""
    idx, csr, speeds, shared = globals()["_CTX"]
    return _solve_one(origin, idx, csr, speeds, shared)


def _load_ferries():
    """Ferry crossings if the OSM extracts are present, else None.

    Reported the same way rail is: a build that quietly dropped ferries would
    leave every island without an airport unreachable, and look identical to
    one that included them.
    """
    try:
        links = osm.ferry_links()
    except FileNotFoundError as exc:
        print(f"ferries:  EXCLUDED -- {exc}")
        return None
    print(f"ferries:  included -- {len(links):,} crossings parsed")
    return links


def _build_all(limit: int | None = None) -> None:
    """Build the graph once, then solve, validate and emit every origin.

    Aborts on the first failing gate -- a partially written dist/ is worse
    than none. `limit` restricts to the first N origins, for smoke-testing.
    """
    lock = _acquire_lock(config.DIST)
    try:
        swept = tiles.sweep_scratch()
        if swept:
            logging.getLogger(__name__).warning(
                "removed %d stale tippecanoe staging file(s) left by an earlier run", swept)
        others = _other_builds()
        if others:
            logging.getLogger(__name__).warning(
                "%d other build-all process(es) are running on this machine (pids %s); "
                "if they are orphans of a killed build, reap them -- they hold graph memory",
                len(others), ", ".join(map(str, others)))
        _build_all_locked(limit)
    finally:
        lock.unlink(missing_ok=True)


def _build_all_locked(limit: int | None) -> None:
    rail_routes = _load_rail()
    ferry_links = _load_ferries()
    idx = nodes.build_index(rail_routes=rail_routes)
    csr = build.build_graph(idx, rail_routes=rail_routes, ferry_links=ferry_links)
    # Graph-level gate: runs once, before any origin is solved, because a
    # disconnected airport is a property of the network rather than of a
    # particular origin -- and per-origin coverage cannot see it.
    validate.check_airport_connectivity(idx, csr)
    # Computed once and reused by check_monotonic_ground below: the ground
    # speed grid does not change between origins, and re-deriving it per
    # origin cost ~4.8s x 157 origins for the same value.
    speeds = ground.cell_speed_kmh(idx)
    # Everything a worker needs that comes from parquet or GDAL is loaded HERE,
    # once, and inherited copy-on-write -- so no forked child ever calls into
    # polars or pyogrio. (See the POLARS_MAX_THREADS note at the top.)
    country = countries.cell_country(idx.cells)
    zone = np.array([transfers.immigration_zone(countries.iso2(c)) if c else ""
                     for c in country])
    cell_class = ground.cell_class(idx)
    # The render grid (land + sea fringe, neighbour table) is the same for
    # every origin; computed once here, inherited copy-on-write.
    shared = {"country": country, "zone": zone, "cell_class": cell_class,
              # Base-grid rings for the zoom <= 6 levels, raw adjacency of the
              # native (mixed-resolution) cells for the finest level.
              "grid": grid.universe(getattr(idx, "base_cells", None) or idx.cells),
              "native": grid.native_edges(idx),
              # Plain dicts: a forked worker must never touch a polars frame.
              "rail_tables": rail_detail.lookup_tables(rail_routes)}

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

    # Origins are independent once the graph exists, and the machine has more
    # than one core. Serially this build took nearly eight hours; the graph is
    # ~1 GB of scipy arrays, so workers are FORKED to inherit it copy-on-write
    # rather than spawned, which would rebuild it once per worker.
    workers = min(_worker_cap(len(idx.cells)), _worker_count(len(origins)))
    shared["workers"] = workers
    try:
        if workers <= 1:
            for origin in origins:
                print(_solve_one(origin, idx, csr, speeds, shared))
        else:
            ctx = multiprocessing.get_context("fork")
            globals()["_CTX"] = (idx, csr, speeds, shared)
            with ctx.Pool(workers, initializer=_watch_parent, initargs=(os.getpid(),)) as pool:
                # A GateFailure in a worker comes back out of imap here (see
                # the class); leaving the block then runs Pool.__exit__, which
                # is terminate(): the other workers are stopped mid-origin
                # rather than left writing into dist/ while this exits.
                for line in _consume(pool, pool.imap(_solve_one_forked, origins)):
                    print(line, flush=True)
    except GateFailure as exc:
        # The same exit from either path: the origin's message, status 1,
        # no traceback.
        raise SystemExit(str(exc)) from exc

    # Only reached once every origin above has succeeded -- and never for a
    # partial run. A --limit smoke test that rewrote index.json would leave
    # dist/ advertising the handful of origins it happened to build, which is
    # indistinguishable from a real build until the site drops to one city.
    if limit is not None:
        print(f"--limit {limit}: index.json left untouched (partial build)")
        return
    index.write_index(origins, config.DIST / "index.json")


def _consume(pool, results):
    """Yield imap results, aborting when a worker has died without reporting.

    The pool replaces a worker that exits for any reason, so the set of worker
    pids changing is the signal that a task's result will never arrive.
    """
    expected = {p.pid for p in pool._pool}
    while True:
        try:
            yield results.next(timeout=WORKER_POLL_S)
        except StopIteration:
            return
        except multiprocessing.TimeoutError:
            current = {p.pid for p in pool._pool}
            if current != expected:
                gone = sorted(expected - current)
                raise GateFailure(
                    f"worker(s) {gone} died without reporting (killed by a signal or the "
                    "OS -- memory pressure, a native crash); aborting the build") from None


def main() -> None:
    # Without a handler Python prints WARNING and above only, so every
    # logger.info the build relies on for "reported, not assumed" -- how many
    # cells were split, stations dropped, airports snapped, borders cut --
    # was discarded. Workers inherit this through fork.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
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
        rail_routes = _load_rail()
        ferry_links = _load_ferries()
        idx = nodes.build_index(rail_routes=rail_routes)
        csr = build.build_graph(idx, rail_routes=rail_routes, ferry_links=ferry_links)
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


# Without this, `python -m transport_maps.cli build-all` imports the module,
# runs nothing and exits 0 -- a build that silently does no work and still
# reports success. Only the `transport-maps` console script has an entry point.
if __name__ == "__main__":
    main()
