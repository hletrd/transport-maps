"""Pipeline entry point."""

import os

# Must precede every import that pulls in polars. Its rayon thread pool does
# not survive fork(): a child that touches polars blocks on the pool's lock
# forever. Eight workers sat at 0% CPU for 37 minutes before this was found.
# The parquet reads here are small; single-threaded costs nothing measurable.
os.environ.setdefault("POLARS_MAX_THREADS", "1")

import argparse
import dataclasses
import gzip
import json
import logging
import multiprocessing
import resource
import subprocess
import sys
import threading
import time
import types
from datetime import UTC, datetime
from pathlib import Path

from transport_maps import _io, config, progress, validate, variants
from transport_maps.contour import bands, grid
from transport_maps.emit import (
    hover,
    index,
    itinerary,
    modes,
    override,
    rail_detail,
    routes_json,
    tiles,
)
from transport_maps.graph import build, ground, nodes
from transport_maps.solve import dijkstra
from transport_maps.sources import _fetch, countries, osm

# One slug grammar, owned by emit.index (where origins.toml is read).
_SLUG_RE = index._SLUG_RE


def _slug(name: str) -> str:
    if not _SLUG_RE.fullmatch(name):
        raise argparse.ArgumentTypeError(
            f"invalid slug {name!r}: letters, digits, '-' and '_' only, "
            "starting with a letter or digit"
        )
    return name


def _slug_list(text: str) -> list[str]:
    slugs = [_slug(x) for x in text.split(",") if x]
    if not slugs:
        # An empty list is not "everything": that would be a full, publishing build.
        raise argparse.ArgumentTypeError("--only needs at least one slug")
    return slugs


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


# Peak resident memory of one worker on the res-6/7 grid, measured from the
# per-origin column rebuild 27 logged (2026-10-02..04): median 8.2 GB, max
# 10.7 GB. Rounded up: an operator asking for more workers is refused by this
# figure, not by the kernel's OOM killer on a machine that also serves others.
WORKER_PEAK_GB = 12.0
# The parent: graph, index and the shared precomputes, before any fork.
PARENT_GB = 20.0


def _requested_workers(n_origins: int, env=None, meminfo: str | None = None) -> int | None:
    """TRANSPORT_MAPS_WORKERS, when set: the operator's worker count, checked
    against the memory actually AVAILABLE now, not the machine's total.

    The default (`_worker_cap`, `_worker_count`) is sized for a 32 GB Mac. On a
    large shared machine -- h200: 1.9 TB, most of it held by inference -- the
    total says nothing about what is free, so the request is refused unless
    WORKER_PEAK_GB per worker plus the parent fits in 80% of MemAvailable.
    Where /proc/meminfo does not exist (macOS) the request is taken as given.
    """
    raw = (env if env is not None else os.environ).get("TRANSPORT_MAPS_WORKERS")
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        raise SystemExit(f"TRANSPORT_MAPS_WORKERS={raw!r} is not a whole number") from None
    if n < 1:
        raise SystemExit("TRANSPORT_MAPS_WORKERS must be at least 1")
    n = min(n, max(1, n_origins))
    if meminfo is None:
        try:
            meminfo = Path("/proc/meminfo").read_text()
        except OSError:
            return n
    avail_kb = next((int(line.split()[1]) for line in meminfo.splitlines()
                     if line.startswith("MemAvailable:")), None)
    if avail_kb is None:
        return n
    need_gb = n * WORKER_PEAK_GB + PARENT_GB
    avail_gb = avail_kb / 2**20
    if need_gb > 0.8 * avail_gb:
        fits = max(1, int((0.8 * avail_gb - PARENT_GB) // WORKER_PEAK_GB))
        raise SystemExit(f"TRANSPORT_MAPS_WORKERS={n} needs about {need_gb:.0f} GB but only "
                         f"{avail_gb:.0f} GB is available (80% of it may be used): "
                         f"{fits} would fit")
    return n


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


_pid_alive = _io.pid_alive


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


#: A build-all worker that is actually building sits far above this. An orphan
#: of a killed build sits at 0.0 % for days -- eight of them (pids 12633-12640,
#: ppid 1, stat SN) were resident for eighteen hours while this was written.
#: scripts/deploy_verify.sh has carried the same threshold, and the same
#: reasoning in a comment, since 6d4ac0f; this is the Python half of it.
BUSY_CPU_PERCENT = 1.0


def _other_builds(*, min_cpu: float = 0.0) -> list[int]:
    """Pids of other build-all processes on this machine, from ps.

    `min_cpu` filters by instantaneous CPU: pass BUSY_CPU_PERCENT to see only
    processes that are working, and 0.0 (the default) to see orphans too. The
    two callers want different answers. A build warns about every match,
    orphans included, because an idle worker still holds its share of the graph
    in memory and the owner should reap it. `reindex` must refuse only for
    processes that will actually overwrite index.json when they finish -- an
    orphan never will, and refusing on one strands the operator between two
    gates giving contradictory advice: deploy_verify.sh passes its own
    (CPU-filtered) check, check_dist then refuses the deploy and names reindex
    as the remedy, and reindex refuses because of a process that died yesterday.
    """
    try:
        out = subprocess.run(["ps", "-axo", "pid=,pcpu=,command="], capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    mine = os.getpid()
    found = []
    for line in out.splitlines():
        pid, _, rest = line.strip().partition(" ")
        cpu, _, cmd = rest.strip().partition(" ")
        if not pid.isdigit() or int(pid) == mine:
            continue
        if "build-all" not in cmd or not ("transport_maps" in cmd or "transport-maps" in cmd):
            continue
        try:
            pcpu = float(cpu)
        except ValueError:
            # ps without a readable pcpu column: treat the process as busy
            # rather than invent an idle one. Refusing is the safe direction.
            pcpu = float("inf")
        if pcpu >= min_cpu:
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


# An origin the land mask cannot place is a bad row in data/origins.toml, and
# the run cannot publish it. What made that a build-killer rather than a
# five-minute edit is WHEN it was discovered: at whatever position the origin
# happened to occupy in the queue. rebuild19 died at origin 970 of 1,464, 26
# hours in, on one city centre the 1:10m outline cuts inside -- and it would
# have died on the next bad row 26 hours after the fix. The pre-flight below
# resolves every selected origin the moment the index exists, which costs one
# dictionary lookup each, and reports EVERY bad row at once.
#
# The snapped bound exists for the reason MAX_SNAPPED_AIRPORT_FRACTION does
# (graph/nodes.py): with a snap in place, a land mask that lost its coastline
# does not fail any of these checks -- every coastal origin simply snaps one
# cell inland and the build passes. A handful of snaps is normal (exactly one
# of 1,464 on 2026-09-14, Kota Kinabalu at 4.2 km); a tenth of the roster
# moving means the mask regressed.
MAX_SNAPPED_ORIGIN_FRACTION = 0.05
# ...but a fraction of a handful means nothing, and applying it to one would
# make `--only kota-kinabalu` -- the exact invocation for investigating the
# city that snaps -- abort with "the land mask lost coverage". A regressed
# mask is a global property and is not visible in twenty rows, so the bound
# waits until the roster is big enough to carry it.
MIN_ORIGINS_FOR_SNAP_BOUND = 100


def _preflight_origins(idx, origins: list[dict]) -> None:
    """Resolve every selected origin against the land mask, before the graph.

    Raises `GateFailure` naming every unresolvable slug, not the first one:
    two bad coordinates should cost one run, not two. Snapped origins are
    logged with their distance -- the snap was silent, so a future roster
    expansion could move a city 13 km with nothing said -- and a mask
    regression that snaps a large share of the roster fails here too.
    """
    log = logging.getLogger(__name__)
    bad: list[str] = []
    snapped: list[tuple[str, float]] = []
    for origin in origins:
        try:
            _, km = dijkstra.snap_origin(idx, origin["lat"], origin["lon"])
        except ValueError as exc:
            bad.append(f"{origin['slug']} ({origin['lat']}, {origin['lon']}): {exc}")
            continue
        if km > 0.0:
            snapped.append((origin["slug"], km))
    if bad:
        raise GateFailure(
            f"{len(bad)} of {len(origins)} origin(s) in data/origins.toml are not "
            "on a land cell and have no land cell within two rings of them. Fix "
            "the coordinate(s) or remove the row(s); the graph was not built.\n  "
            + "\n  ".join(bad)
        )
    if snapped:
        worst = sorted(snapped, key=lambda r: -r[1])
        log.warning(
            "%d of %d origin(s) snapped to the nearest land cell (%s)",
            len(snapped), len(origins),
            ", ".join(f"{slug} {km:.1f} km" for slug, km in worst[:8])
            + (", ..." if len(worst) > 8 else ""))
        share = len(snapped) / len(origins)
        if len(origins) >= MIN_ORIGINS_FOR_SNAP_BOUND and share > MAX_SNAPPED_ORIGIN_FRACTION:
            raise GateFailure(
                f"{share:.1%} of origins snapped to a neighbouring cell, above the "
                f"{MAX_SNAPPED_ORIGIN_FRACTION:.0%} bound. One or two is a "
                "gazetteer point falling outside a 1:10m coastline; this many "
                "means the land mask lost coverage. Check the mask before "
                "spending a day on the solve."
            )


def _peak_rss_mb() -> float:
    """This process's resident high-water mark so far, in MB.

    `ru_maxrss` is in bytes on macOS and in kilobytes on Linux (getrusage(2)
    on each). It is a high-water mark, not a per-origin figure: a worker's
    value only rises across the origins it runs, so the largest one logged
    against a pid is that worker's peak -- the number a worker cap has to
    fit, and one nothing recorded before (PR-4: workers measured at 11-12 GB
    against a cap modelled on about a third of that).
    """
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1 << 20) if sys.platform == "darwin" else peak / 1024


def _solve_one(origin: dict, idx, csr, speeds, shared: dict) -> str:
    """Solve and emit one origin. Returns the table row to print."""
    slug = origin["slug"]
    # A coordinate too far from any land cell to snap is a bad row in
    # data/origins.toml, not a bug in the solver -- so it is a per-origin gate
    # failure that names the slug, not a traceback out of a worker. Every
    # other gate below already reports itself this way; this one did not,
    # which is how one unvalidated coordinate could kill a 39-hour build.
    try:
        source = dijkstra.origin_node(idx, origin["lat"], origin["lon"])
    except ValueError as exc:
        raise GateFailure(f"{slug}: {exc}") from exc
    minutes, predecessors = dijkstra.solve_from(csr, source, with_predecessors=True)

    variant = shared.get("variant")
    coverage = validate.check_coverage(minutes, idx, shared["reachable"])
    # An exclusion variant has no coverage floor to speak of: without flights
    # Honolulu reaches Hawaii and nothing else, correctly. What it must still
    # do is reach SOMETHING -- a solve that reached no land at all is broken
    # whichever modes it was allowed.
    floor = validate.MIN_COVERAGE if variant is None else 0.0
    if coverage < floor or (variant is not None and coverage == 0.0):
        raise GateFailure(
            f"{slug}: coverage {coverage:.1%} below {floor:.0%}"
            + (f" in the no-{variant} variant" if variant else "")
        )
    validate.check_monotonic_ground(idx, minutes, speeds,
                                    country=shared["country"], zone=shared["zone"],
                                    crossing_min=shared["border_min"])

    # The variants are built without the zoom-7+ level: three quarters of
    # every origin's band tiles, and three full sets would not fit on the web
    # host beside the real one (variants.py). They keep the reading tier.
    slim = variant is not None
    fc = bands.band_feature_collection(idx, minutes[: idx.n_cells],
                                       grid=shared["grid"], native=shared["native"],
                                       skip_native=slim, flags=shared["band_flags"])
    validate.check_bands_cover(idx, shared["grid"], shared["native"], fc, skip_native=slim)

    root = shared.get("out_root", config.DIST)
    out = root / "origins"
    out.mkdir(parents=True, exist_ok=True)
    # Every gate has passed; nothing of this origin has been replaced yet. From
    # here until `finish` below its record says "writing", so a build that
    # stops between two of the nine files -- the pool terminated by another
    # worker's gate, a kill -- leaves an origin check_dist refuses and
    # --skip-existing rebuilds, not one that is quietly half of each build.
    stamp = shared.get("stamp")
    if stamp is not None:
        progress.begin(root, origin, stamp)
    tiles.write_pmtiles(fc, out / f"{slug}.pmtiles", workers=shared.get("workers"),
                        max_zoom=variants.VARIANT_MAX_ZOOM if slim else tiles.MAX_ZOOM)
    # Computed ONCE per origin and handed to every writer below. Each used to
    # derive its own -- the representative child four times over, each a
    # Python loop over 13.8 million cells -- and the override needs all three.
    parents = shared["hover_parents"]
    rep_arr = hover.representative_array(shared["hover_groups"], minutes[: idx.n_cells])
    rep = {p: int(v) for p, v in enumerate(rep_arr) if v >= 0}
    last = itinerary.arrival_airport_per_node(idx, minutes, predecessors)
    acc = modes.mode_minutes_per_node(idx, minutes, predecessors, cell_class=shared["cell_class"])

    hover.write_hover(idx, minutes[: idx.n_cells], out / f"{slug}.bin", parents=parents, rep=rep)
    hover.write_reading(idx, minutes[: idx.n_cells], out / f"{slug}.r6.bin",
                        layout=shared["reading"])
    # The route behind the fine reading wherever it differs from the coarse
    # cell's. A variant needs both as much as the full set: without them it
    # read the ~20 km area's representative, and with ferries avoided printed
    # Tinian at Saipan's 7 h 38 -- faster than the full map's 9 h 32, which no
    # map with fewer modes can be.
    override.write_override(idx, last, acc, rep_arr, shared["base_hover"],
                            shared["reading"], out / f"{slug}.over.bin")
    routes_json.write_routes(idx, minutes, predecessors, out / f"{slug}.json")
    itinerary.write_itinerary(idx, minutes, predecessors, out / f"{slug}.air.bin",
                              parents=parents, rep=rep, last=last)
    modes.write_modes(idx, minutes, predecessors, out / f"{slug}.modes.bin",
                      cell_class=shared["cell_class"], parents=parents, rep=rep, acc=acc)
    rail_detail.write_rail_detail(idx, minutes, predecessors, shared.get("rail_tables"),
                                  out / f"{slug}.rail.bin", out / f"{slug}.rail.json",
                                  parents=parents, rep=rep)
    # LAST: the record is what says the nine files above are one origin.
    if stamp is not None:
        progress.finish(root, origin, stamp)

    size_kb =(out / f"{slug}.pmtiles").stat().st_size // 1024
    # Read last, after every writer has run, so the origin's own peak is in it.
    return (f"{slug:<20}{coverage:>9.1%}{len(fc['features']):>8}{size_kb:>12}"
            f"{os.getpid():>8}{_peak_rss_mb():>10,.0f}")


@dataclasses.dataclass(frozen=True)
class BuildContext:
    """Everything a forked worker reads, built once in the parent.

    Handed to each worker as the pool initializer's argument. Under the fork
    start method `Pool` passes `initargs` to the child through fork() itself,
    never through pickle (measured: an argument whose __reduce__ raises
    arrives intact, at the parent's array addresses), so the graph and the
    shared arrays stay copy-on-write exactly as they did when this was a
    module global the parent wrote into its own namespace before forking
    (`globals()["_CTX"]`, S2). Frozen, and `shared` a read-only view, so a
    worker cannot rebind what its siblings were also given.
    """
    idx: object
    csr: object
    speeds: object
    shared: types.MappingProxyType


# Set in each worker by _init_worker and never in the parent: the parent hands
# the context over explicitly instead of leaving it lying in its globals.
_WORKER_CONTEXT: BuildContext | None = None


def _init_worker(parent_pid: int, context: BuildContext) -> None:
    """Pool initializer: watch the parent, then keep the build's context."""
    global _WORKER_CONTEXT
    _watch_parent(parent_pid)
    _WORKER_CONTEXT = context


def _solve_one_forked(origin: dict) -> str:
    """Pool entry point. Reads the context the initializer was handed."""
    context = _WORKER_CONTEXT
    if context is None:
        raise RuntimeError("a build worker started without its BuildContext")
    return _solve_one(origin, context.idx, context.csr, context.speeds, context.shared)


def _still_to_build(origins: list[dict], shared: dict) -> list[dict]:
    """The origins `--skip-existing` must still build, in roster order.

    An origin is left alone only when its completion record is "complete"
    under this run's key -- the same inputsHash and the same graph -- and
    every file it lists is still there at the recorded size
    (`progress.problem`). Everything else is built again: no record, a run
    that stopped inside it, other inputs, a file gone or resized.
    """
    root, stamp = shared["out_root"], shared["stamp"]
    todo, why = [], []
    for origin in origins:
        problem = progress.problem(root, origin, stamp)
        if problem is not None:
            todo.append(origin)
            why.append(f"{origin['slug']}: {problem}")
    print(f"--skip-existing: {len(origins) - len(todo):,} of {len(origins):,} origin(s) are "
          f"complete for inputs {stamp.inputs_hash} / graph {stamp.graph_hash}; "
          f"{len(todo):,} to build", flush=True)
    for line in why[:5]:
        print(f"  rebuilding {line}", flush=True)
    if len(why) > 5:
        print(f"  ... and {len(why) - 5:,} more", flush=True)
    return todo


def _log_reading_cost(path: Path) -> None:
    """What one origin's reading array costs raw and on the wire.

    Reporting only. Every failure here is swallowed: a build that has solved
    553 origins must not be lost to a log line, and this one reads a 10 MB
    file and compresses it.
    """
    if not path.exists():
        return
    raw = path.stat().st_size
    # Level 1 is what nginx serves: gzip_comp_level is not set in the site
    # config, and its default is 1. Reporting level 6 here would understate
    # the bytes a visitor actually receives.
    try:
        wire = len(gzip.compress(path.read_bytes(), 1))
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "could not measure %s on the wire: %s", path.name, exc)
        return
    print(f"reading tier: {path.name} {raw:,} B raw, {wire:,} B gzipped "
          f"(ratio {wire / raw:.3f}) -- one fetch per origin switch", flush=True)


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


def _check_inputs(exclude: str | None = None) -> None:
    """Ask every upstream whether the raw inputs this build reads have changed,
    and fetch what has, before anything reads one (G2).

    Explicit and up front, rather than left to whichever module reads an input
    first, for three reasons: the build log says in one place what each input
    is; a refused crawl or an unreachable input with no cached copy stops the
    build in its first minutes instead of hours in; and every input is settled
    before `build_identity` records them, so index.json names the snapshot the
    build read. Each check happens once per process (sources/_fetch.py), so
    the modules reading these later get the same answer.

    Offline (`--offline`, TRANSPORT_MAPS_OFFLINE=1) every one of these reads
    its cache and nothing is asked.
    """
    from transport_maps.sources import (
        airports,
        geofabrik,
        landmask,
        roads,
        routes,
        urban,
    )

    print("inputs:   " + ("offline -- cached copies only, no upstream asked" if _fetch.offline()
                          else "checking each raw input against its upstream"), flush=True)
    airports._download()          # OurAirports
    landmask._sources()           # Natural Earth land, lakes, ice shelves
    countries._source()           # Natural Earth countries
    urban._source()               # Natural Earth populated places
    roads._sources()              # the five GRIP4 archives
    geofabrik.refresh()           # the OSM extracts, against Geofabrik's state.txt
    if exclude != "air":
        # The Wikipedia crawl and the Wikidata resolution: articles and titles
        # past their max age are fetched again (sources/routes.py). A no-air
        # variant never reads the route network, so it does not ask.
        routes.route_network()
    changed = [f"{fp.path.name} ({fp.status})" for fp in _fetch.checked()
               if fp.status in ("downloaded", "updated", "kept")]
    if changed:
        print("inputs:   " + ", ".join(changed), flush=True)


def _build_all(limit: int | None = None, only: list[str] | None = None,
               exclude: str | None = None, skip_existing: bool = False) -> None:
    """Build the graph once, then solve, validate and emit every origin.

    Aborts on the first failing gate -- a partially written dist/ is worse
    than none. `limit` restricts to the first N origins and `only` to the
    named slugs; either makes a PARTIAL build that never rewrites index.json.
    `skip_existing` leaves alone every origin already complete for this
    build's inputs (transport_maps.progress), which is how a run that died is
    resumed; what it publishes is what a run from scratch would.
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
        _build_all_locked(limit, only, exclude, skip_existing)
    finally:
        lock.unlink(missing_ok=True)


def _build_all_locked(limit: int | None, only: list[str] | None = None,
                      exclude: str | None = None, skip_existing: bool = False) -> None:
    started = datetime.now(UTC)
    # Sampled here, not at the end. index.json is written as the last statement
    # of this function, and build_identity()/mode_detail() read the git head,
    # calibration.toml and origins.toml at call time -- so a long build stamped
    # itself with the tree as it stood when it FINISHED, not with the inputs it
    # actually used.
    # Inputs before identity: build_identity records what they were.
    _check_inputs(exclude)
    identity = index.build_identity(started)
    modes_detail = index.mode_detail()
    rail_routes = _load_rail()
    ferry_links = _load_ferries()
    # Selected BEFORE the graph exists, so the pre-flight below can check
    # exactly the rows this run will solve -- not the whole file, which would
    # abort a `--only seoul` smoke test over a bad coordinate in a city it was
    # never going to touch.
    origins = index.load_origins()
    if only:
        known = {o["slug"] for o in origins}
        missing = [s for s in only if s not in known]
        if missing:
            raise SystemExit(f"--only names origins not in origins.toml: {missing}")
        origins = [o for o in origins if o["slug"] in set(only)]
    if limit is not None:
        origins = origins[:limit]
    partial = limit is not None or bool(only)
    # A full variant rebuild overwrites the files of a finished one origin by
    # origin. Until it finishes the tree is half old and half new, so it stops
    # being offered now and is offered again by the marker written at the end.
    if exclude is not None and not partial:
        variants.withdraw(variants.variant_dir(config.DIST, exclude))

    idx = nodes.build_index(rail_routes=rail_routes)
    # Before the graph, because the graph is the expensive half and a bad
    # coordinate does not need it. See _preflight_origins: this is the gate
    # that turns a lost day into a message in the first two minutes.
    try:
        _preflight_origins(idx, origins)
    except GateFailure as exc:
        raise SystemExit(str(exc)) from exc
    # Everything a worker needs that comes from parquet or GDAL is loaded HERE,
    # once, and inherited copy-on-write -- so no forked child ever calls into
    # polars or pyogrio. (See the POLARS_MAX_THREADS note at the top.) And
    # before the graph, which needs the same four arrays: build_graph used to
    # derive country and zone three more times (hex_edges, then rail, ferry
    # and spans each through _border_rules) and the road class twice more, a
    # ~4 M-cell raster pass each time (PR-5, R5).
    country = countries.cell_country(idx.cells)
    zone = ground.cell_zones(country)
    cell_class = ground.cell_class(idx)
    # Reused by check_monotonic_ground in every origin as well: the ground
    # speed grid does not change between origins, and re-deriving it per
    # origin cost ~4.8s x every origin for the same value.
    speeds = ground.cell_speed_kmh(idx, classes=cell_class)
    csr = build.build_graph(idx, rail_routes=rail_routes, ferry_links=ferry_links,
                            exclude=exclude, speeds=speeds, country=country, zone=zone)
    # Graph-level gate: runs once, before any origin is solved, because a
    # disconnected airport is a property of the network rather than of a
    # particular origin -- and per-origin coverage cannot see it. Without
    # flights every airport off the largest landmass is "disconnected" by
    # design, so the no-air variant is the one graph it cannot judge.
    if exclude != "air":
        validate.check_airport_connectivity(idx, csr)
    # The resident solver's copy of this graph (service/bundle.py): written
    # here, from the graph every origin below is solved on, so an uncharted
    # departure is answered by exactly the model the map was drawn with. Not
    # in dist/ -- it is 1.2 GB the page never reads; the deploy ships it
    # separately. Variants are not served on demand, so they write none.
    if exclude is None:
        from transport_maps.service import bundle

        bundle.write_bundle(config.BUILD / "solver", idx.cells, idx._split, csr.shape[0],
                            csr, identity, n_airports=len(idx.airports),
                            n_stations=len(idx.stations))
        logging.getLogger(__name__).info("solver bundle written to %s", config.BUILD / "solver")
    # The render grid (land + sea fringe, neighbour table) is the same for
    # every origin; computed once here, inherited copy-on-write.
    hover_parents = hover.hover_cells(idx)
    # Base-grid rings for the zoom <= 6 levels, raw adjacency of the native
    # (mixed-resolution) cells for the finest level.
    render_grid = grid.universe(getattr(idx, "base_cells", None) or idx.cells)
    shared = {"country": country, "zone": zone, "cell_class": cell_class,
              "grid": render_grid,
              "native": grid.native_edges(idx),
              # Which cells wrap the antimeridian, and each cell's resolution:
              # what every band dissolve of every origin asks of each cell.
              # Once here; per origin it was ~115 s of boundary tests (R2).
              "band_flags": bands.precompute_flags(idx, render_grid),
              # Plain dicts: a forked worker must never touch a polars frame.
              "rail_tables": rail_detail.lookup_tables(rail_routes),
              # Where every base cell's minutes go in the reading tier's block
              # array. It depends only on the grid, so it is built ONCE here
              # and inherited copy-on-write by the pool: per origin it would be
              # 4,091,715 cells of index arithmetic x every origin, for an answer that
              # cannot change between origins.
              "reading": hover.reading_layout(idx),
              "variant": exclude,
              # The origin-independent half of the hover representative, and
              # each base cell's hover parent (for the override): once here,
              # not once per writer per origin.
              "hover_parents": hover_parents,
              "hover_groups": hover.hover_groups(idx, hover_parents),
              "base_hover": hover.base_hover_index(idx, hover_parents),
              # What the two per-origin gates read of the grid and of
              # calibration.toml: the cells outside Antarctica, ~9 s of h3
              # calls per origin, and the land-border minute (R3, PR-16).
              "reachable": validate.reachable_in_principle(idx),
              "border_min": ground._land_border_min(),
              "out_root": variants.variant_dir(config.DIST, exclude)}
    # What each origin's completion record is keyed on (transport_maps.progress):
    # the identity sampled at the start plus a digest of the graph itself,
    # which is where the data inputs the identity cannot see come in.
    shared["stamp"] = progress.Stamp.of(
        identity, progress.graph_hash(csr, hover_parents, cell_class, shared["rail_tables"]),
        exclude)

    # hover_cells.bin depends only on the graph, not on any origin, so it is
    # safe to write eagerly. index.json is different: it lists the origins the
    # frontend expects to find files for, so it must wait until every origin
    # below has actually succeeded -- writing it first would leave it naming
    # origins whose per-origin files an aborted run never produced.
    # A variant shares these with the full set -- same cells, same order --
    # and must not rewrite files the live full set is being served from.
    if exclude is None:
        index.write_hover_cells(idx, config.DIST / "hover_cells.bin", parents=hover_parents)
    # Same reasoning: the block ordering depends only on the graph, and it is
    # ONE file for every origin rather than one per origin, because the set
    # of res-3 parents holding land does not vary with the departure city.
    if exclude is None:
        index.write_reading_parents(idx, config.DIST / "reading_parents.bin")

    print(f"{'origin':<20}{'coverage':>10}{'bands':>8}{'pmtiles KB':>12}{'pid':>8}{'peak MB':>10}")

    # Origins are independent once the graph exists, and the machine has more
    # than one core. Serially this build took nearly eight hours; the graph is
    # ~1 GB of scipy arrays, so workers are FORKED to inherit it copy-on-write
    # rather than spawned, which would rebuild it once per worker.
    todo = _still_to_build(origins, shared) if skip_existing else origins
    workers = (_requested_workers(len(todo))
               or min(_worker_cap(len(idx.cells)), _worker_count(len(todo))))
    shared["workers"] = workers
    try:
        if workers <= 1:
            for origin in todo:
                print(_solve_one(origin, idx, csr, speeds, shared))
        else:
            ctx = multiprocessing.get_context("fork")
            context = BuildContext(idx, csr, speeds, types.MappingProxyType(shared))
            with ctx.Pool(workers, initializer=_init_worker,
                          initargs=(os.getpid(), context)) as pool:
                # A GateFailure in a worker comes back out of imap here (see
                # the class); leaving the block then runs Pool.__exit__, which
                # is terminate(): the other workers are stopped mid-origin
                # rather than left writing into dist/ while this exits.
                # Unordered: a row is printed when its origin finishes, so one
                # slow origin no longer hides the dozens finished behind it.
                # Nothing published depends on the order -- index.json and
                # the marker are written from `origins`, after the loop.
                for line in _consume(pool, pool.imap_unordered(_solve_one_forked, todo)):
                    print(line, flush=True)
    except GateFailure as exc:
        # The same exit from either path: the origin's message, status 1,
        # no traceback.
        raise SystemExit(str(exc)) from exc

    # Only reached once every origin above has succeeded -- and never for a
    # partial run. A --limit smoke test that rewrote index.json would leave
    # dist/ advertising the handful of origins it happened to build, which is
    # indistinguishable from a real build until the site drops to one city.
    # The number this format costs on the wire, measured rather than modelled.
    # The raw size is a constant (readingParentCount x readingSlots x 2); the
    # gzipped size is not knowable until a real time field exists, and nginx
    # serves these gzipped -- deploy/worldmap.atik.kr.conf gzips
    # `location ~* \.bin$` at the default level 1. Measured on the first origin
    # built, so the plan's estimate is replaced by a fact in the build log.
    # `origins` can be empty (`--limit 0`), and a LOG LINE must never be able
    # to fail a build that has already succeeded -- which an IndexError here
    # would do, at the last statement before index.json is written.
    if origins and exclude is None:
        _log_reading_cost(config.DIST / "origins" / f"{origins[0]['slug']}.r6.bin")

    if partial:
        print("partial build (--limit / --only): index.json left untouched")
        return
    # Published from the records, not from "the loop ended": every origin the
    # index or the marker is about to name must be complete under THIS run's
    # key, whether this run wrote it or found it. A worker that returned
    # without recording, or a file removed behind the build's back, stops the
    # publication here instead of reaching the site.
    unfinished = [(o["slug"], why) for o in origins
                  if (why := progress.problem(shared["out_root"], o, shared["stamp"]))]
    if unfinished:
        raise SystemExit(
            f"{len(unfinished)} of {len(origins)} origin(s) are not complete for this build, so "
            "nothing was published: "
            + "; ".join(f"{slug}: {why}" for slug, why in unfinished[:5])
            + (" ..." if len(unfinished) > 5 else ""))
    if exclude is not None:
        # Never index.json: that describes the full set. The marker is what
        # `reindex` reads to decide the variant is complete enough to offer.
        variants.write_marker(variants.variant_dir(config.DIST, exclude), exclude,
                              [o["slug"] for o in origins], identity)
        print(f"variant no-{exclude} complete: {len(origins)} origins")
        return
    index.write_index(origins, config.DIST / "index.json",
                      hover_cell_count=len(hover_parents),
                      reading_parent_count=len(shared["reading"].parents),
                      graph={"rail": bool(getattr(idx, "has_rail", False)),
                             "ferry": ferry_links is not None and len(ferry_links) > 0},
                      identity=identity, modes_detail=modes_detail,
                      solver_bundle=config.BUILD / "solver")


#: The index fields that describe the ARTIFACTS, not the checkout, and that the
#: page's guards compare against the arrays. `reindex` refuses when any has
#: moved since the dist/ was built rather than silently republishing.
_CURRENT_INDEX_CONSTANTS = {
    "bandEdgesMin": lambda: list(config.BAND_EDGES_MIN),
    "solveRes": lambda: config.SOLVE_RES,
    "modeChannels": lambda: list(modes.CHANNELS),
    # hoverRes was the omission that mattered most. It is the resolution of
    # hover_cells.bin, and the page binary-searches that array by cell id
    # (app.js: cellIndex). Republish an index whose hoverRes has moved and
    # every lookup misses, so every land cell reads "Open water." -- past
    # check_dist, which only compares hoverCellCount against the file's
    # length, and past the page's own guard, which compares the same two.
    "hoverRes": lambda: config.HOVER_RES,
    # fineRes is written into the index and read back by the page's outline
    # detail; a stale value describes a refinement the artifacts do not have.
    "fineRes": lambda: config.FINE_RES,
    # unreachable is the sentinel every uint16 array is written with. If the
    # code's value has moved, the page would test the arrays against a
    # threshold they were not written with.
    "unreachable": lambda: config.UNREACHABLE,
    # The reading tier's three format constants. readingRes is to
    # reading_parents.bin what hoverRes is to hover_cells.bin, and
    # readingSlots is worse than either if it moves: the page would still
    # find the right block and then read the wrong slot inside it, so every
    # land cell would report a plausible time from somewhere else nearby.
    "readingRes": lambda: config.READING_RES,
    "readingParentRes": lambda: config.READING_PARENT_RES,
    "readingSlots": lambda: config.READING_SLOTS,
    # The layout version the artifacts were written under (docs/contract.md,
    # "Versioning"). It goes up exactly when a file changes meaning, width or
    # order, so stamping today's number over a dist/ built under another one
    # would tell the page the old arrays have the new layout. An index.json
    # from before the field existed has no key and still reindexes, as for
    # every other key here (J1b).
    "contractVersion": lambda: index.CONTRACT_VERSION,
}


def _reindex(dist: Path | None = None) -> None:
    """Rewrite dist/index.json alone, from the artifacts already on disk.

    index.json is written by the parent process at the END of a build, from the
    emit.index module that parent imported at the START. A sixteen-hour build
    therefore publishes the index emitter as it stood sixteen hours earlier.
    The 553-origin build started 2026-09-10 04:23 misses buildId, builtAt,
    hoverCellCount, modeChannels, railDetail and graph -- every one of them
    added to the emitter between 05:51 and 06:00.

    Those absences are not cosmetic. The page's mixed-build guard
    (`meta.hoverCellCount`) and its channel-order guard (`meta.modeChannels`)
    both fall back to trusting the arrays, and `railDetail` absent means the
    ~204 MB of .rail.bin/.rail.json such a build ships is never fetched: the
    rail itinerary silently disappears from the site.

    Re-running the build to correct one 40 KB file is not a remedy, so this
    rewrites that file and nothing else. It takes the same lock a build takes
    and refuses when another build-all is running, it lists only origins whose
    whole file set is present and the right length, and it carries the previous
    index's identity forward rather than stamping today's checkout as if it had
    produced the artifacts.
    """
    dist = dist or config.DIST
    log = logging.getLogger(__name__)
    lock = _acquire_lock(dist)
    try:
        others = _other_builds(min_cpu=BUSY_CPU_PERCENT)
        if others:
            raise SystemExit(
                f"build-all is running (pids {', '.join(map(str, others))}) without holding "
                f"{dist / LOCK_NAME}; it will overwrite index.json when it finishes. Wait for it.")
        idle = set(_other_builds()) - set(others)
        if idle:
            log.warning(
                "ignoring %d build-all process(es) below %.1f%% CPU (pids %s): orphans of a "
                "killed build never finish, so they will not overwrite index.json. Reap them.",
                len(idle), BUSY_CPU_PERCENT, ", ".join(map(str, sorted(idle))))

        cells = dist / "hover_cells.bin"
        if not cells.exists():
            raise SystemExit(f"{cells} missing: there is no build here to index")
        size = cells.stat().st_size
        if size == 0 or size % 8:
            raise SystemExit(f"{cells} is {size} bytes, not a whole number of uint64 cell ids")
        n_cells = size // 8

        previous = {}
        index_path = dist / "index.json"
        if index_path.exists():
            try:
                previous = json.loads(index_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                log.warning("existing index.json is unreadable (%s); writing a fresh one", exc)

        # An origin is publishable only if every file the page fetches is there
        # and the fixed-width ones have one entry per hover cell. Listing an
        # origin whose array is short is the blank-globe failure this command
        # exists to prevent, so a short array excludes it rather than warning.
        widths = {".bin": 2, ".air.bin": 2, ".modes.bin": 2 * len(modes.CHANNELS)}

        # The reading array is keyed on reading_parents.bin, not on
        # hover_cells.bin, so it is checked against its own directory. A dist/
        # built before the tier existed has neither the directory nor the
        # arrays and must still be indexable, so an ABSENT directory means the
        # tier is absent and no origin is excluded for lacking it. A directory
        # that IS present makes {slug}.r6.bin required at its own width -- half
        # a build is the blank-globe failure this command exists to prevent.
        parents_path = dist / "reading_parents.bin"
        reading_bytes = 0
        n_parents = None
        if parents_path.exists():
            psize = parents_path.stat().st_size
            if psize == 0 or psize % 8:
                raise SystemExit(f"{parents_path} is {psize} bytes, not a whole "
                                 "number of uint64 cell ids")
            n_parents = psize // 8
            reading_bytes = n_parents * config.READING_SLOTS * 2

        present, skipped, rail_seen = [], [], False
        for origin in index.load_origins():
            slug = origin["slug"]
            base = dist / "origins"
            why = [f"{slug}{suf} missing" for suf in (*widths, ".json", ".pmtiles")
                   if not (base / f"{slug}{suf}").exists()]
            why += [f"{slug}{suf} has {(base / f'{slug}{suf}').stat().st_size // w} entries, "
                    f"expected {n_cells}"
                    for suf, w in widths.items()
                    if (base / f"{slug}{suf}").exists()
                    and (base / f"{slug}{suf}").stat().st_size != n_cells * w]
            if reading_bytes:
                r6 = base / f"{slug}.r6.bin"
                if not r6.exists():
                    why.append(f"{slug}.r6.bin missing")
                elif r6.stat().st_size != reading_bytes:
                    why.append(f"{slug}.r6.bin is {r6.stat().st_size} bytes, "
                               f"expected {reading_bytes}")
            if why:
                skipped.append((slug, why[0]))
                continue
            present.append(origin)
            rail_seen = rail_seen or (base / f"{slug}.rail.bin").exists()

        if not present:
            raise SystemExit(f"no origin under {dist / 'origins'} has a complete file set")
        for slug, why in skipped[:10]:
            log.warning("reindex skips %s: %s", slug, why)
        if len(skipped) > 10:
            log.warning("reindex skips %d more origins", len(skipped) - 10)

        # The identity of a build cannot be recovered from its artifacts, so it
        # is carried forward, never invented: stamping today's git head would
        # assert that this checkout produced files it did not. `builtAt` is the
        # exception -- hover_cells.bin is written before the first origin, so
        # its mtime IS when the build started.
        identity = {k: previous[k]
                    for k in ("inputsHash", "buildId", "builtAt", "gitHead", "inputs")
                    if k in previous}
        identity.setdefault(
            "builtAt",
            datetime.fromtimestamp(cells.stat().st_mtime, UTC).replace(microsecond=0).isoformat())
        identity["reindexedAt"] = datetime.now(UTC).replace(microsecond=0).isoformat()

        # Same reasoning as the identity above, applied to the four fields that
        # describe the ARTIFACTS rather than this checkout. write_index derives
        # them from today's code and today's calibration.toml, which for a
        # sixteen-hour build is sixteen hours after the graph was weighted --
        # the in-flight build read calibration.toml at ~04:28 and the file was
        # rewritten at 05:34:33, which is the evidence T20 was landed on.
        #
        # modeDetail is prose the visitor reads in the route panel, so it is
        # carried forward rather than re-derived. The rest cannot be
        # carried forward, because the page's guards depend on them agreeing
        # with the arrays: if they have moved, the artifacts were built by
        # different code and rewriting index.json alone would republish a new
        # legend over old tiles. That is a refusal, not a warning.
        drifted = [k for k in _CURRENT_INDEX_CONSTANTS
                   if k in previous and previous[k] != _CURRENT_INDEX_CONSTANTS[k]()]
        if drifted:
            raise SystemExit(
                "the code has moved since this dist/ was built: "
                + "; ".join(f"{k} was {previous[k]!r}, is now "
                            f"{_CURRENT_INDEX_CONSTANTS[k]()!r}" for k in drifted)
                + ". Rewriting index.json alone would publish today's "
                  "constants over yesterday's artifacts. Rebuild instead.")

        modes_detail = previous.get("modeDetail")
        if modes_detail is None:
            log.warning(
                "the previous index.json has no modeDetail, so the route panel's mode prose is "
                "sampled from calibration.toml NOW, not from the constants the artifacts were "
                "built with. It may describe speeds this build did not use.")

        graph = dict(previous.get("graph") or {})
        graph["rail"] = rail_seen
        index.write_index(present, index_path, hover_cell_count=n_cells,
                          reading_parent_count=n_parents,
                          graph=graph, identity=identity, rail_detail=rail_seen,
                          modes_detail=modes_detail, solver_bundle=config.BUILD / "solver")
        print(f"index.json rewritten: {len(present)} origins, {n_cells:,} hover cells, "
              f"rail detail {'present' if rail_seen else 'absent'}, "
              f"built {identity['builtAt']}, {len(skipped)} origin(s) skipped")
    finally:
        lock.unlink(missing_ok=True)


#: The static files the page loads beside the per-origin arrays, each with the
#: module whose `build(out)` writes it. None depends on the graph or on any
#: origin, so they are not part of build-all; and until this command existed
#: nothing called those `build` functions at all, so the copies in dist/ were
#: made by hand and could not be reproduced (E6 / O6, AA13, C11-D8).
#: `water.pmtiles`, the fourth static file check_dist requires, is still
#: scripts/build_water_tiles.py: it needs the OSM water polygons and
#: tippecanoe, not a JSON emitter.
ASSETS = {
    "places.json": "places",
    "airports.json": "airports_json",
    "borders.json": "borders",
}


def _assets(dist: Path | None = None, names: list[str] | None = None) -> None:
    """(Re)write the static page assets into `dist` (default dist/).

    Under the build lock, so it cannot interleave with a build-all or a
    reindex rewriting the same directory. Each file is written atomically by
    its emitter (`_io.atomic_write`), so a failure leaves the previous copy in
    place rather than half a file.
    """
    import importlib

    dist = dist or config.DIST
    names = names or list(ASSETS)
    unknown = [n for n in names if n not in ASSETS]
    if unknown:
        raise SystemExit(f"unknown asset(s) {unknown}; choose from {list(ASSETS)}")
    lock = _acquire_lock(dist)
    try:
        for name in names:
            # Imported here, not at the top: borders pulls in pyogrio and
            # places httpx, and neither belongs in the parent a build forks.
            emitter = importlib.import_module(f"transport_maps.emit.{ASSETS[name]}")
            count = emitter.build(dist / name)
            print(f"{name}: {count:,} entries -> {dist / name}", flush=True)
    finally:
        lock.unlink(missing_ok=True)


def _consume(pool, results):
    """Yield imap results, aborting when a worker has died without reporting.

    The pool replaces a worker that exits for any reason, so the set of worker
    pids changing is the signal that a task's result will never arrive.
    `pool._pool` is private API; verified against CPython 3.14.2.
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

    # `solve` and `index` used to be separate entry points with their own file
    # layout and no gates -- `index` could publish an index.json for origins
    # with no files. One path builds everything; --only is the single-origin
    # smoke test, through the same gates.
    #
    # "Never publishing" was too strong and this is what it withholds: a
    # partial run leaves index.json untouched, so the SITE never advertises
    # the handful of origins it built. It does still write
    # dist/hover_cells.bin and dist/origins/{slug}.*, which is what makes it a
    # smoke test of the real emit path -- and means a partial run over a
    # populated dist/ overwrites those origins' arrays in place.
    build_all = sub.add_parser(
        "build-all", help="build the graph once and solve, validate and emit every origin"
    )
    build_all.add_argument(
        "--limit",
        type=int,
        default=None,
        help="build only the first N origins (writes their arrays into dist/origins; "
             "index.json is left untouched, so the site does not advertise them)",
    )
    build_all.add_argument(
        "--exclude",
        choices=variants.EXCLUDABLE,
        default=None,
        help="build the exclusion variant that never uses this mode, into "
             "dist/v/no-<mode>/ (no zoom-7+ tiles, no res-6 reading tier)",
    )
    build_all.add_argument(
        "--only",
        type=_slug_list,
        default=None,
        help="comma-separated origin slugs to build (writes their arrays into "
             "dist/origins; index.json is left untouched, so the site does not advertise them)",
    )

    build_all.add_argument(
        "--skip-existing",
        action="store_true",
        help="resume: leave alone every origin whose completion record (<root>/.progress/) "
             "is complete for this build's inputs and graph with its files at the recorded "
             "sizes; build the rest, then publish as a full run would. Pair it with "
             "--offline to resume on the inputs the dead run read: a changed upstream "
             "changes the graph, and then nothing is skipped",
    )
    build_all.add_argument(
        "--offline",
        action="store_true",
        help="ask no upstream whether a raw input changed: read every input from "
             "data/cache as it is, and fail on one that is not there. For reproducing a "
             f"past build or resuming one (also: {_fetch.OFFLINE_ENV}=1)",
    )

    # Not a second way to publish: reindex writes index.json and nothing else,
    # from artifacts a build already produced. It exists because index.json is
    # emitted by the parent at the end of a long build, using the emitter that
    # parent imported at the start -- so a build that outlives an emitter change
    # publishes a stale index for artifacts that are not stale.
    sub.add_parser(
        "reindex",
        help="rewrite dist/index.json from the artifacts on disk (no solving, no rebuild)",
    )

    assets = sub.add_parser(
        "assets",
        help="write the static page assets (places.json, airports.json, borders.json) "
             "into dist/; no graph, no origins",
    )
    assets.add_argument("names", nargs="*", metavar="NAME",
                        help=f"which to write, of {', '.join(ASSETS)} (default: all)")
    assets.add_argument("--offline", action="store_true",
                        help="read GeoNames and the boundary lines from data/cache as they "
                             "are, asking no upstream")

    args = parser.parse_args()
    config.ensure_dirs()
    if getattr(args, "offline", False):
        _fetch.set_offline(True)

    if args.command == "build-all":
        _build_all(limit=args.limit, only=args.only, exclude=args.exclude,
                   skip_existing=args.skip_existing)
    elif args.command == "reindex":
        _reindex()
    elif args.command == "assets":
        _assets(names=args.names)


# Without this, `python -m transport_maps.cli build-all` imports the module,
# runs nothing and exits 0 -- a build that silently does no work and still
# reports success. Only the `transport-maps` console script has an entry point.
if __name__ == "__main__":
    main()
