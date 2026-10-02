import argparse
import os
import signal
import subprocess
import sys
from typing import ClassVar

import h3
import numpy as np
import pytest
from scipy.sparse import csr_matrix

from transport_maps import cli, config
from transport_maps.cli import _slug
from transport_maps.sources import roads


def test_slug_accepts_a_simple_name():
    assert _slug("seoul") == "seoul"
    assert _slug("new_york-2") == "new_york-2"


def test_slug_rejects_path_traversal():
    with pytest.raises(argparse.ArgumentTypeError):
        _slug("../../etc/passwd")


def test_slug_rejects_path_separators():
    with pytest.raises(argparse.ArgumentTypeError):
        _slug("a/b")


# W1 (plan/2026-09-10-c2-gates-and-tests.md). CPython 3.12+ warns on every
# fork() from a process with more than one OS thread, and this test process
# has four before any test runs: importing transport_maps.cli loads polars and
# pyarrow, whose native pools start at import (measured: 1 thread -> 4; polars
# alone 1 -> 2, pyarrow alone 1 -> 3). The tests marked with this fork on
# purpose, because `_build_all` does -- it is the path they exist to test.
#
# Silencing it there and only there is safe because the hazard the warning
# names cannot pass unseen in these tests. A child deadlocks on a lock that
# another thread held at the fork; the children here run the stubbed
# pipeline, which keeps polars and GDAL out of workers exactly as the real
# build does (it preloads their results in the parent), and every one of
# these tests arms a 15 s SIGALRM that turns a hung pool into a TimeoutError,
# i.e. red. What the filter hides is the advice, not the failure.
#
# Narrow on purpose: this exact message, this category, these tests. Any
# other warning they raise -- another DeprecationWarning included -- still
# shows, and the production build still prints this one (its exit criterion,
# a forkserver/spawn pool, is S2's and is not this).
FORK_WARNING = (r"This process \(pid=\d+\) is multi-threaded, "
                r"use of fork\(\) may lead to deadlocks in the child")
forks_a_threaded_process = pytest.mark.filterwarnings(f"ignore:{FORK_WARNING}:DeprecationWarning")


def test_the_fork_warning_filter_matches_that_warning_and_no_other():
    """The filter is only safe if it is narrow, and only useful if it matches
    the warning CPython actually raises, so both are checked against a real
    one: a thread is started and the process forks, and the warning that
    comes back must be swallowed by the filter while a different
    DeprecationWarning, and the same text in another category, are not.

    Mutations performed and reverted, each -> red: `is multi-threaded` ->
    `is threaded` in FORK_WARNING (the real warning is no longer matched);
    FORK_WARNING -> `.*` (the unrelated DeprecationWarning is swallowed).
    """
    import re
    import threading
    import warnings

    stop = threading.Event()
    t = threading.Thread(target=stop.wait)
    t.start()
    try:
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            pid = os.fork()
            if pid == 0:
                os._exit(0)
            os.waitpid(pid, 0)
    finally:
        stop.set()
        t.join()
    real = [w for w in seen if issubclass(w.category, DeprecationWarning)
            and "fork" in str(w.message)]
    assert real, f"no fork warning from a threaded fork: {[str(w.message) for w in seen]}"

    def survives(message: str, category: type[Warning]) -> bool:
        with warnings.catch_warnings(record=True) as got:
            warnings.simplefilter("always")
            # What pytest builds from the mark: an anchored, case-insensitive
            # regex on the message, and the category.
            warnings.filterwarnings("ignore", message=FORK_WARNING, category=DeprecationWarning)
            warnings.warn(message, category, stacklevel=1)
        return bool(got)

    assert re.match(FORK_WARNING, str(real[0].message))
    assert not survives(str(real[0].message), DeprecationWarning), "the filter misses the real warning"
    assert survives("datetime.utcnow() is deprecated", DeprecationWarning), "the filter is not narrow"
    assert survives(str(real[0].message), RuntimeWarning), "the filter ignores the category"


# Where the stubbed solver-bundle writer records its calls, as (out, keyword
# arguments) -- kept out of `written`, whose length several tests count.
BUNDLES: list = []


def _stub_pipeline(monkeypatch, written, coverages):
    """Replace every collaborator `_build_all` calls with a cheap stand-in, so
    the test exercises only the sequencing of `_build_all` itself: two fake
    origins, "first" and "second", `coverages` supplying `check_coverage`'s
    return value for each BY ORIGIN, in origins order. `written` records every
    emitted file path (in the calling process only: a forked worker's appends
    never reach the parent).

    The input check (G2) is stubbed too: it reads every raw input, and these
    tests have none. tests/cli/test_check_inputs.py tests it.
    """
    monkeypatch.setattr(cli, "_check_inputs", lambda exclude=None: None)

    class FakeIdx:
        n_cells = 1
        cells: ClassVar[list[str]] = ["dummy"]
        airports: ClassVar[list[str]] = []  # check_airport_connectivity runs for real below
        stations: ClassVar[tuple[str, ...]] = ()
        # The reading tier is indexed on the uniform res-READING_RES grid and
        # refuses to guess one, because the digits it reads are identical for
        # a res-7 cell and its res-6 parent -- so a fallback to `cells` would
        # put seven siblings in one slot at exactly the right file length.
        # One REAL cell, not "dummy": the emitter parses these as h3 ids and
        # checks their resolution, which is the point of the refusal.
        base_cells: ClassVar[list[str]] = [
            h3.latlng_to_cell(37.5665, 126.9780, config.READING_RES)]
        base_index: ClassVar[np.ndarray] = np.zeros(1, dtype=np.int64)
        fine: ClassVar[np.ndarray] = np.zeros(1, dtype=bool)
        _split: ClassVar[frozenset] = frozenset()

        def try_cell_index(self, cell):
            return None

    monkeypatch.setattr(cli.nodes, "build_index", lambda **kw: FakeIdx())
    # The solver bundle goes to the real data/build; a test must never write it.
    from transport_maps.service import bundle as solver_bundle

    BUNDLES.clear()
    monkeypatch.setattr(solver_bundle, "write_bundle",
                        lambda out, *a, **k: BUNDLES.append((out, k)))
    # The staging sweep touches a directory shared with every build on the
    # machine; the sequencing tests must never reach it.
    monkeypatch.setattr(cli.tiles, "sweep_scratch", lambda: 0)
    # The OSM extracts are a real, multi-gigabyte cache: the sequencing tests
    # must not depend on them (nor pay the 2.75 s polars UDF per _build_all).
    monkeypatch.setattr(cli.osm, "rail_routes",
                        lambda **kw: (_ for _ in ()).throw(FileNotFoundError("stubbed: no extracts")))
    monkeypatch.setattr(cli.osm, "ferry_links",
                        lambda **kw: (_ for _ in ()).throw(FileNotFoundError("stubbed: no extracts")))
    # check_airport_connectivity is NOT mocked (it's a graph-level gate this
    # stub is meant to exercise honestly), so it feeds this straight into
    # scipy's connected_components -- a plain object() blows up there with
    # "'object' object has no attribute 'dtype'". One node, no airports, is
    # enough to satisfy it trivially.
    monkeypatch.setattr(cli.build, "build_graph", lambda idx, **kw: csr_matrix((1, 1)))
    monkeypatch.setattr(
        cli.index, "load_origins",
        lambda: [
            {"slug": "first", "name": "First", "lat": 0.0, "lon": 0.0},
            {"slug": "second", "name": "Second", "lat": 1.0, "lon": 0.0},
        ],
    )
    monkeypatch.setattr(cli.index, "write_hover_cells", lambda idx, out, **kw: None)
    monkeypatch.setattr(cli.hover, "hover_cells", lambda idx: ["dummy-parent"])
    # cell_speed_kmh would otherwise call h3.cell_to_boundary("dummy") for real
    # and blow up; _build_all now computes it once and threads it through to
    # check_monotonic_ground (M5), so this stub needs a stand-in too.
    monkeypatch.setattr(cli.ground, "cell_speed_kmh", lambda idx, **kw: np.array([1.0]))
    # _build_all preloads these in the parent so forked workers never touch
    # polars or GDAL; on a one-cell fake index they must be stand-ins too.
    monkeypatch.setattr(cli.countries, "cell_country", lambda cells: np.array(["KOR"]))
    monkeypatch.setattr(cli.countries, "iso2", lambda a3: "KR")
    monkeypatch.setattr(roads, "cell_class", lambda cells: np.array([1]))
    monkeypatch.setattr(cli.ground, "cell_class", lambda idx: np.array([1]))
    # The origin's latitude doubles as its position in `coverages`, threaded
    # through the stubbed solve so check_coverage can look its value up by
    # ORIGIN. Keyed on call order (an iterator) this was wrong under fork:
    # every worker inherits its own copy of the iterator, so each origin
    # would have drawn the first value.
    # ONE stub for both entry points, because the real ones are one function:
    # `origin_node` is `snap_origin(...)[0]`, and the build's pre-flight calls
    # `snap_origin` directly. Two independent stubs could pass a test the
    # shipped code would fail, which is exactly the drift the pre-flight and
    # the solve share an implementation to prevent -- so the double shares one
    # too. `FakeIdx` has no `cell_at`, deliberately: it is a one-node stand-in
    # for the build's SEQUENCING, not for the land mask, and the real
    # resolution path is covered against a hand-built NodeIndex in
    # tests/cli/test_origin_preflight.py.
    monkeypatch.setattr(cli.dijkstra, "snap_origin", lambda idx, lat, lon: (int(lat), 0.0))
    monkeypatch.setattr(cli.dijkstra, "origin_node",
                        lambda idx, lat, lon: cli.dijkstra.snap_origin(idx, lat, lon)[0])
    monkeypatch.setattr(
        cli.dijkstra, "solve_from",
        lambda csr, source, with_predecessors=False: (np.array([float(source)]), np.array([-9999])),
    )
    monkeypatch.setattr(cli.validate, "check_coverage",
                        lambda minutes, idx, reachable=None: coverages[int(minutes[0])])
    # Computed once in the parent from each cell's latitude; "dummy" has none.
    monkeypatch.setattr(cli.validate, "reachable_in_principle", lambda idx: np.ones(1, bool))
    monkeypatch.setattr(
        cli.validate, "check_monotonic_ground", lambda idx, minutes, speeds, **kw: None
    )
    monkeypatch.setattr(cli.bands, "band_feature_collection",
                        lambda idx, minutes, grid=None, native=None, **kw: {"features": []})
    monkeypatch.setattr(cli.grid, "native_edges",
                        lambda idx: (np.zeros(0, np.int32), np.zeros(0, np.int32), np.ones(1, bool)))
    monkeypatch.setattr(cli.validate, "check_bands_cover", lambda *a, **k: None)
    monkeypatch.setattr(cli.bands, "precompute_flags", lambda idx, grid: None)
    # The render grid is preloaded in the parent like the arrays above; the
    # fake index's cell is not a real H3 id, so it needs a stand-in too.
    monkeypatch.setattr(cli.grid, "universe",
                        lambda cells: (list(cells), np.full((len(cells), 6), -1, dtype=np.int32),
                                       np.zeros(len(cells), dtype=np.int8)))

    def _fake_write(out, *_args):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")
        written.append(out)

    monkeypatch.setattr(cli.tiles, "write_pmtiles", lambda fc, out, **kw: _fake_write(out))
    monkeypatch.setattr(cli.hover, "write_hover", lambda idx, minutes, out, **kw: _fake_write(out))
    # The per-origin products every writer now shares (cli._solve_one): on a
    # one-cell fake index they are stand-ins, like the arrays above.
    monkeypatch.setattr(cli.hover, "hover_groups", lambda idx, parents: None)
    monkeypatch.setattr(cli.hover, "base_hover_index", lambda idx, parents: np.zeros(1, np.int64))
    monkeypatch.setattr(cli.hover, "representative_array", lambda groups, minutes: np.zeros(1, np.int64))
    monkeypatch.setattr(cli.itinerary, "arrival_airport_per_node", lambda idx, m, p: np.full(1, -1))
    monkeypatch.setattr(cli.modes, "mode_minutes_per_node", lambda idx, m, p, **kw: np.zeros((1, 6)))
    monkeypatch.setattr(cli.override, "write_override", lambda *a: _fake_write(a[-1]))
    monkeypatch.setattr(
        cli.routes_json, "write_routes", lambda idx, minutes, pred, out: _fake_write(out)
    )
    monkeypatch.setattr(
        cli.itinerary, "write_itinerary", lambda idx, minutes, pred, out, **kw: _fake_write(out)
    )
    monkeypatch.setattr(
        cli.modes, "write_modes", lambda idx, minutes, pred, out, **kw: _fake_write(out)
    )
    monkeypatch.setattr(
        cli.rail_detail, "write_rail_detail",
        lambda idx, minutes, pred, routes, out_bin, out_json, **kw: (_fake_write(out_bin), _fake_write(out_json))
    )


def test_index_json_is_not_written_when_an_origin_aborts_partway(monkeypatch, tmp_path):
    """Regression guard: index.json lists the origins the frontend expects
    files for, so it must not be written until every origin has succeeded.
    Writing it before the loop (the original ordering) would leave it naming
    "second" even though its per-origin files were never produced.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    index_calls: list = []
    monkeypatch.setattr(
        cli.index, "write_index", lambda origins, out, **kw: index_calls.append(list(origins))
    )
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 0.0])  # "second" fails coverage

    with pytest.raises(SystemExit, match="second"):
        cli._build_all()

    assert index_calls == []  # never reached: aborted before the write
    assert len(written) == 8  # "first"'s pmtiles/hover/over/routes/air/modes/rail.bin/rail.json


def test_index_json_is_written_once_every_origin_succeeds(monkeypatch, tmp_path):
    """Companion to the abort test: confirms the fix does not simply delete
    the call -- a fully successful run still writes index.json, exactly once,
    with every origin.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    index_calls: list = []
    monkeypatch.setattr(
        cli.index, "write_index", lambda origins, out, **kw: index_calls.append(list(origins))
    )
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 1.0])

    cli._build_all()

    assert len(index_calls) == 1
    assert [o["slug"] for o in index_calls[0]] == ["first", "second"]
    assert len(written) == 16  # both origins' eight files each (the .over.bin included)


def test_a_limited_build_does_not_rewrite_index_json(monkeypatch, tmp_path):
    """--limit is a smoke test, not a deploy.

    Rewriting index.json from a partial run leaves dist/ advertising only the
    origins that run happened to build, which looks exactly like a real build
    until the live site drops to one city.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    _stub_pipeline(monkeypatch, written, [1.0, 1.0])
    wrote_index: list = []
    monkeypatch.setattr(cli.index, "write_index",
                        lambda origins, out, **kw: wrote_index.append(out))

    cli._build_all(limit=1)
    assert wrote_index == [], "a partial build rewrote index.json"

    cli._build_all()
    assert wrote_index, "a full build must still write index.json"


def test_the_build_reports_whether_rail_and_ferries_are_included(monkeypatch, tmp_path, capsys):
    """A build that silently drops rail or ferries looks exactly like one that
    included them, and the difference is hours across Europe and every island
    without an airport. Both must announce which graph was produced.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    _stub_pipeline(monkeypatch, written, [1.0, 1.0])
    monkeypatch.setattr(cli.osm, "rail_routes",
                        lambda **kw: (_ for _ in ()).throw(FileNotFoundError("no extracts")))
    monkeypatch.setattr(cli.osm, "ferry_links",
                        lambda **kw: (_ for _ in ()).throw(FileNotFoundError("no extracts")))

    cli._build_all()
    out = capsys.readouterr().out
    # Per LINE, not over the whole output: `"EXCLUDED" in out` was satisfied by
    # the rail line alone, so the ferry report -- the suite's only assertion
    # about it -- was unguarded. Printing "ferries:  included" after a
    # FileNotFoundError left this green.
    lines = {ln.split(":", 1)[0].strip(): ln for ln in out.splitlines() if ":" in ln}
    for mode in ("rail", "ferries"):
        assert mode in lines, f"the build report says nothing about {mode}: {out}"
        assert "EXCLUDED" in lines[mode], (
            f"{mode} raised FileNotFoundError and the build reported "
            f"{lines[mode].strip()!r}")


@forks_a_threaded_process
def test_a_gate_failure_in_a_forked_worker_aborts_the_run(monkeypatch, tmp_path):
    """With enough origins the workers are FORKED, and multiprocessing's
    worker loop catches only Exception. The coverage gate used to raise
    SystemExit inside the worker: that killed the worker, the pool quietly
    respawned it, the task's result never arrived and imap blocked forever --
    a build that neither finishes nor reports. The failure must reach the
    parent and abort the run, as it does on the serial path.

    Bounded by an alarm so a regression fails instead of hanging the suite.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    monkeypatch.setattr(cli, "_worker_count", lambda n_origins: 2)
    written: list = []
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 0.0])  # "second" fails coverage
    index_calls: list = []
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: index_calls.append(1))

    def hung(signum, frame):
        raise TimeoutError("_build_all is hanging: the worker's gate failure never reached the parent")

    previous = signal.signal(signal.SIGALRM, hung)
    signal.alarm(15)
    try:
        with pytest.raises(SystemExit, match="second"):
            cli._build_all()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert index_calls == []


@forks_a_threaded_process
def test_forked_workers_get_the_build_context_from_the_initializer_unpickled(
        monkeypatch, tmp_path, capsys):
    """S2: the forked path runs every origin from a BuildContext handed to the
    pool initializer -- not from a global the parent writes into its own
    namespace -- and the context crosses by fork, never by pickle: a pickled
    copy would duplicate the graph in every worker instead of sharing it
    copy-on-write. Here pickling the context raises, so a pool that pickled
    its initargs (the spawn start method, or the context sent with each task)
    fails the build; and the parent must end with no context of its own.

    Mutations performed and reverted, each red: the context sent to a worker
    as a task argument (it fails on "was pickled"); `_init_worker` not
    storing it; the parent setting the module global itself (the `_CTX`
    shape this replaced).
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    monkeypatch.setattr(cli, "_worker_count", lambda n_origins: 2)
    _stub_pipeline(monkeypatch, [], coverages=[1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: None)

    def no_pickle(self, protocol):
        raise RuntimeError("the BuildContext was pickled")
    monkeypatch.setattr(cli.BuildContext, "__reduce_ex__", no_pickle)

    def hung(signum, frame):
        raise TimeoutError("the forked build hung")
    previous = signal.signal(signal.SIGALRM, hung)
    signal.alarm(15)
    try:
        cli._build_all()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    rows = {ln.split()[0] for ln in capsys.readouterr().out.splitlines() if ln.split()}
    assert {"first", "second"} <= rows
    assert cli._WORKER_CONTEXT is None, "the parent kept a build context in its globals"
    assert not hasattr(cli, "_CTX")


@forks_a_threaded_process
def test_a_worker_killed_by_a_signal_aborts_the_run_instead_of_hanging(monkeypatch, tmp_path):
    """multiprocessing.Pool respawns a worker that dies of a signal and the
    task's result never arrives, so imap blocks forever: an OOM kill or a
    native crash at hour six left the build neither finished nor failed.
    The parent must notice the replaced worker and abort.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    monkeypatch.setattr(cli, "_worker_count", lambda n_origins: 2)
    monkeypatch.setattr(cli, "WORKER_POLL_S", 0.5)
    written: list = []
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 1.0])

    def die_on_second(minutes, idx, reachable=None):
        if int(minutes[0]) == 1:
            os.kill(os.getpid(), signal.SIGKILL)
        return 1.0
    monkeypatch.setattr(cli.validate, "check_coverage", die_on_second)

    def hung(signum, frame):
        raise TimeoutError("_build_all is hanging: the killed worker was never noticed")

    previous = signal.signal(signal.SIGALRM, hung)
    signal.alarm(15)
    try:
        with pytest.raises(SystemExit, match="died without reporting"):
            cli._build_all()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_a_second_build_refuses_while_the_lock_is_held(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], [1.0, 1.0])       # so a wrongly acquired lock runs fast, not for real
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: None)
    (tmp_path / cli.LOCK_NAME).write_text(f"{os.getpid()} 2026-09-10T00:00:00Z\n")
    with pytest.raises(SystemExit, match="held by a running build"):
        cli._build_all()
    assert (tmp_path / cli.LOCK_NAME).exists(), "the refused build removed someone else's lock"


def test_a_stale_lock_is_reported_not_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], [1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: None)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()                                                    # a pid that has exited
    (tmp_path / cli.LOCK_NAME).write_text(f"{dead.pid} 2026-09-10T00:00:00Z\n")
    with pytest.raises(SystemExit, match="STALE"):
        cli._build_all()


def test_the_lock_is_released_after_a_run(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    _stub_pipeline(monkeypatch, written, [1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: None)
    cli._build_all()
    assert not (tmp_path / cli.LOCK_NAME).exists()


def test_only_builds_the_named_origins_through_the_same_path_and_never_publishes(monkeypatch, tmp_path):
    """`solve` and `index` were separate entry points with their own layout and
    no gates; --only is the single-origin smoke test through the real path."""
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    _stub_pipeline(monkeypatch, written, [1.0, 1.0])
    wrote_index: list = []
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: wrote_index.append(out))

    cli._build_all(only=["second"])
    assert wrote_index == [], "a partial build rewrote index.json"
    assert {p.name.split(".")[0] for p in written} == {"second"}
    assert len(written) == 8  # one origin's eight files, the .over.bin included

    with pytest.raises(SystemExit, match="not in origins.toml"):
        cli._build_all(only=["nowhere"])


def test_a_full_build_stamps_identity_count_and_graph_flags_into_index_json(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], [1.0, 1.0])
    calls: list = []
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: calls.append(kw))
    cli._build_all()
    kw = calls[0]
    assert kw["hover_cell_count"] == 1
    assert kw["graph"] == {"rail": False, "ferry": False}
    assert set(kw["identity"]) == {"inputsHash", "buildId", "builtAt", "gitHead", "inputs"}
    # The solver bundle is told the node layout, so the service can read an
    # itinerary off it (service/bundle.py, journey_legs). Mutation performed
    # and reverted: drop the two keywords from cli's write_bundle call -> red.
    assert [k for _out, k in BUNDLES] == [{"n_airports": 0, "n_stations": 0}]


def test_each_origin_row_logs_its_process_and_peak_memory(monkeypatch, tmp_path, capsys):
    """R4: the per-origin row carries the pid and the resident high-water mark,
    so a worker's peak is a measured number in the build log. The figure is
    held against `ps`, which reports this process's current RSS in KB: a peak
    can be no lower than that, and no higher than the machine. A wrong unit
    either way (getrusage is bytes on macOS, KB on Linux) misses by 1024x and
    fails one bound or the other -- tried both, both red."""
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], [1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: None)
    cli._build_all()
    rows = [ln.split() for ln in capsys.readouterr().out.splitlines()
            if ln.split()[:1] in (["first"], ["second"])]
    assert len(rows) == 2
    rss_kb = int(subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())],
                                capture_output=True, text=True, check=True).stdout)
    physical_mb = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1 << 20)
    for row in rows:
        assert int(row[-2]) == os.getpid()
        peak_mb = float(row[-1].replace(",", ""))
        assert rss_kb / 1024 * 0.9 <= peak_mb <= physical_mb, (peak_mb, rss_kb, physical_mb)


def test_the_build_derives_border_and_speed_inputs_once_for_the_graph(monkeypatch, tmp_path):
    """R5: country, zone, road class and speeds are derived once, before the
    graph, and build_graph receives those very arrays -- the same ones every
    worker inherits -- instead of deriving its own. Mutations performed and
    reverted, each red: dropping `country=` / `speeds=` from the build_graph
    call, and `classes=` from cell_speed_kmh."""
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], [1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: None)
    country, classes, speeds = np.array(["KOR"]), np.array([1]), np.array([1.0])
    lookups: list = []
    monkeypatch.setattr(cli.countries, "cell_country",
                        lambda cells: (lookups.append(1), country)[1])
    monkeypatch.setattr(cli.ground, "cell_class", lambda idx: classes)
    speed_kw: dict = {}
    monkeypatch.setattr(cli.ground, "cell_speed_kmh",
                        lambda idx, **kw: (speed_kw.update(kw), speeds)[1])
    graph_kw: dict = {}
    monkeypatch.setattr(cli.build, "build_graph",
                        lambda idx, **kw: (graph_kw.update(kw), csr_matrix((1, 1)))[1])
    worker_shared: list = []
    solve_one = cli._solve_one
    monkeypatch.setattr(cli, "_solve_one",
                        lambda o, i, c, s, shared: (worker_shared.append(shared),
                                                    solve_one(o, i, c, s, shared))[1])
    cli._build_all()
    assert lookups == [1]
    assert speed_kw.get("classes") is classes
    assert graph_kw.get("country") is country and graph_kw.get("speeds") is speeds
    shared = worker_shared[0]
    assert shared["country"] is country
    assert graph_kw.get("zone") is shared["zone"], "the graph and the workers saw different zones"


def test_worker_cap_drops_to_five_above_three_million_cells():
    assert cli._worker_cap(3_000_001) == 5
    assert cli._worker_cap(500_000) == 8


@pytest.mark.parametrize("cmd", ["solve", "index"])
def test_solve_and_index_subcommands_are_gone(monkeypatch, cmd):
    """They wrote a layout the page could not read and published index.json
    for origins with no files (A7); argparse must reject them (exit 2)."""
    monkeypatch.setattr(sys, "argv", ["transport-maps", cmd])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_only_with_no_slug_is_an_error_not_a_full_build():
    with pytest.raises(argparse.ArgumentTypeError):
        cli._slug_list("")
    with pytest.raises(argparse.ArgumentTypeError):
        cli._slug_list(",")


def test_the_build_stamps_itself_before_it_solves_anything(monkeypatch, tmp_path):
    """`build_identity` and `mode_detail` read the git head, calibration.toml
    and origins.toml AT CALL TIME. Called as the last statement of the build --
    where they were -- a sixteen-hour run recorded the checkout as it stood
    when it stopped: for the 553-origin build that is a git head 38 commits
    ahead and hashes of two files rewritten 70 minutes after the graph had
    already read them, so `inputsHash` named inputs the artifacts were not
    built from.

    The ordering, not the value, is the invariant: both must be sampled before
    the first origin is solved, and the sampled values must be what is written.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    order: list[str] = []
    written: list = []
    monkeypatch.setattr(cli.index, "build_identity",
                        lambda started=None: (order.append("identity"), {"buildId": "B"})[1])
    monkeypatch.setattr(cli.index, "mode_detail",
                        lambda: (order.append("modes"), {"rail": "M"})[1])
    seen: list = []
    monkeypatch.setattr(cli.index, "write_index",
                        lambda origins, out, **kw: (order.append("write"), seen.append(kw))[1])
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 1.0])
    solve_one = cli._solve_one
    monkeypatch.setattr(cli, "_solve_one",
                        lambda *a, **k: (order.append("solve"), solve_one(*a, **k))[1])

    cli._build_all()

    assert order[:2] == ["identity", "modes"], f"stamped after solving: {order}"
    assert order[-1] == "write"
    assert seen[0]["identity"] == {"buildId": "B"}
    assert seen[0]["modes_detail"] == {"rail": "M"}


def test_the_reading_cost_log_never_fails_a_build(tmp_path, capsys):
    """It is reporting only, and it runs after 553 origins have succeeded.

    An IndexError or an OSError here would lose a sixteen-hour build to a log
    line -- and the first version could do exactly that: it indexed
    `origins[0]` unguarded, so `--limit 0` crashed at the last statement
    before index.json is written.

    Mutation performed and reverted: drop the `if not path.exists(): return`
    guard -> red; drop the `if origins:` guard in _build_all_locked and run
    with limit=0 -> red (IndexError).
    """
    # absent: silent, no raise
    cli._log_reading_cost(tmp_path / "nothing.r6.bin")
    assert capsys.readouterr().out == ""

    # a real file: reports raw and compressed bytes
    payload = (tmp_path / "x.r6.bin")
    payload.write_bytes(b"\x00\x01" * 5000)
    cli._log_reading_cost(payload)
    out = capsys.readouterr().out
    assert "10,000 B raw" in out and "gzipped" in out, out

    # unreadable: warns, does not raise
    bad = tmp_path / "bad.r6.bin"
    bad.write_bytes(b"\x00" * 16)
    bad.chmod(0o000)
    try:
        cli._log_reading_cost(bad)
    finally:
        bad.chmod(0o644)


def test_a_zero_limit_build_does_not_crash_on_the_cost_log(monkeypatch, tmp_path):
    """`--limit 0` leaves `origins` empty, and the cost log indexes it."""
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    _stub_pipeline(monkeypatch, written, [])
    monkeypatch.setattr(cli.index, "write_index",
                        lambda origins, out, **kw: written.append("index"))
    cli._build_all(limit=0)
    assert "index" not in written, "a partial build must not rewrite index.json"


def test_a_bad_origin_aborts_before_the_graph_is_built_and_names_every_one(
        monkeypatch, tmp_path):
    """The pre-flight, proved by RUNNING the build rather than by reading its
    source.

    `tests/cli/test_origin_preflight.py` covers what `_preflight_origins` does
    against a hand-built NodeIndex, and asserts the call's position in the
    source. Source order is a weak assertion on its own -- it passes for a call
    that is unreachable, or one whose result is discarded. This one takes the
    build path end to end: a roster with two unresolvable coordinates must exit
    naming BOTH, with `build_graph` never called and not one byte written.

    Mutations performed and reverted, each red:
      - delete the `_preflight_origins` call -> build_graph runs and the abort
        comes from the solve loop, naming one origin, after files are written;
      - move it below `csr = build.build_graph(...)` -> `graph` is non-empty;
      - drop the try/except around it -> GateFailure escapes, not SystemExit;
      - collect only the first bad origin -> "second" is absent.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 1.0])

    # Both stub origins are unresolvable. The real snap raises ValueError here;
    # so does this, through the same shared stub the solve would have used.
    def _nowhere(idx, lat, lon):
        raise ValueError("origin is not on a land cell, and no land cell lies "
                         "within two rings of it")
    monkeypatch.setattr(cli.dijkstra, "snap_origin", _nowhere)

    graph: list = []
    real_build_graph = cli.build.build_graph
    monkeypatch.setattr(cli.build, "build_graph",
                        lambda idx, **kw: (graph.append(1), real_build_graph(idx, **kw))[1])

    with pytest.raises(SystemExit) as exit_info:
        cli._build_all()

    message = str(exit_info.value)
    assert "first" in message and "second" in message, (
        f"the pre-flight named only some of the bad origins: {message}")
    assert "2 of 2" in message, f"the count is missing or wrong: {message}"
    assert graph == [], "the graph was assembled before the coordinates were checked"
    assert written == [], "a file was written for a run that could never publish"


def test_what_the_grid_alone_decides_is_computed_once_and_handed_to_every_origin(
        monkeypatch, tmp_path):
    """R3 / H2: the per-origin gates and writers read three things that depend
    on the grid alone, and the parent computes each ONCE: the cells outside
    Antarctica that `check_coverage` counts (13.8 million h3 calls per origin
    before), the land-border minute `check_monotonic_ground` charges, and the
    hover parent list -- which `hover_cells.bin`, `index.json`'s
    `hoverCellCount` and every per-origin writer must share, so it is the
    same list object, not a recomputation that merely agrees (F7).

    Mutations performed and reverted, each red: `_solve_one` passing no mask
    (`check_coverage` gets None); no `crossing_min`; `write_hover_cells`
    called without `parents`; `hover_cell_count` from a fresh `hover_cells`.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    monkeypatch.setattr(cli, "_worker_count", lambda n_origins: 1)
    _stub_pipeline(monkeypatch, [], coverages=[1.0, 1.0])
    seen: dict = {"mask_calls": 0, "mask": [], "crossing": [], "parents": [], "hover_cells": 0}
    mask = np.ones(1, bool)

    def reachable(idx):
        seen["mask_calls"] += 1
        return mask

    def coverage(minutes, idx, reachable=None):
        seen["mask"].append(reachable)
        return 1.0

    def hover_cells(idx):
        seen["hover_cells"] += 1
        return ["dummy-parent"]

    def write_hover(idx, minutes, out, parents=None, **kw):
        seen["parents"].append(parents)
        out.write_bytes(b"x")

    monkeypatch.setattr(cli.validate, "reachable_in_principle", reachable)
    monkeypatch.setattr(cli.ground, "_land_border_min", lambda: 45.0)
    monkeypatch.setattr(cli.validate, "check_coverage", coverage)
    monkeypatch.setattr(cli.validate, "check_monotonic_ground",
                        lambda idx, minutes, speeds, **kw: seen["crossing"].append(kw.get("crossing_min")))
    monkeypatch.setattr(cli.hover, "hover_cells", hover_cells)
    monkeypatch.setattr(cli.index, "write_hover_cells",
                        lambda idx, out, parents=None: seen.__setitem__("cells_file", parents))
    monkeypatch.setattr(cli.hover, "write_hover", write_hover)
    monkeypatch.setattr(cli.index, "write_index",
                        lambda origins, out, **kw: seen.__setitem__("count", kw["hover_cell_count"]))

    cli._build_all()

    assert seen["mask_calls"] == 1 and seen["hover_cells"] == 1
    assert len(seen["mask"]) == 2 and all(m is mask for m in seen["mask"])
    assert seen["crossing"] == [45.0, 45.0]
    one = seen["parents"][0]
    assert one is not None and all(p is one for p in seen["parents"])
    assert seen["cells_file"] is one, "hover_cells.bin was written from another list"
    assert seen["count"] == len(one)
