import argparse
import signal
from typing import ClassVar

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from transport_maps import cli
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


def _stub_pipeline(monkeypatch, written, coverages):
    """Replace every collaborator `_build_all` calls with a cheap stand-in, so
    the test exercises only the sequencing of `_build_all` itself: two fake
    origins, "first" and "second", `coverages` supplying `check_coverage`'s
    return value for each BY ORIGIN, in origins order. `written` records every
    emitted file path (in the calling process only: a forked worker's appends
    never reach the parent).
    """
    class FakeIdx:
        n_cells = 1
        cells: ClassVar[list[str]] = ["dummy"]
        airports: ClassVar[list[str]] = []  # check_airport_connectivity runs for real below

    monkeypatch.setattr(cli.nodes, "build_index", lambda **kw: FakeIdx())
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
    monkeypatch.setattr(cli.index, "write_hover_cells", lambda idx, out: None)
    # cell_speed_kmh would otherwise call h3.cell_to_boundary("dummy") for real
    # and blow up; _build_all now computes it once and threads it through to
    # check_monotonic_ground (M5), so this stub needs a stand-in too.
    monkeypatch.setattr(cli.ground, "cell_speed_kmh", lambda idx: np.array([1.0]))
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
    monkeypatch.setattr(cli.dijkstra, "origin_node", lambda idx, lat, lon: int(lat))
    monkeypatch.setattr(
        cli.dijkstra, "solve_from",
        lambda csr, source, with_predecessors=False: (np.array([float(source)]), np.array([-9999])),
    )
    monkeypatch.setattr(cli.validate, "check_coverage",
                        lambda minutes, idx: coverages[int(minutes[0])])
    monkeypatch.setattr(
        cli.validate, "check_monotonic_ground", lambda idx, minutes, speeds, **kw: None
    )
    monkeypatch.setattr(cli.bands, "band_feature_collection",
                        lambda idx, minutes, grid=None, native=None: {"features": []})
    monkeypatch.setattr(cli.grid, "native_edges",
                        lambda idx: (np.zeros(0, np.int32), np.zeros(0, np.int32), np.ones(1, bool)))
    monkeypatch.setattr(cli.validate, "check_bands_cover", lambda *a, **k: None)
    # The render grid is preloaded in the parent like the arrays above; the
    # fake index's cell is not a real H3 id, so it needs a stand-in too.
    monkeypatch.setattr(cli.grid, "universe",
                        lambda cells: (list(cells), np.full((len(cells), 6), -1, dtype=np.int32),
                                       np.zeros(len(cells), dtype=np.int8)))

    def _fake_write(out, *_args):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")
        written.append(out)

    monkeypatch.setattr(cli.tiles, "write_pmtiles", lambda fc, out: _fake_write(out))
    monkeypatch.setattr(cli.hover, "write_hover", lambda idx, minutes, out: _fake_write(out))
    monkeypatch.setattr(
        cli.routes_json, "write_routes", lambda idx, minutes, pred, out: _fake_write(out)
    )
    monkeypatch.setattr(
        cli.itinerary, "write_itinerary", lambda idx, minutes, pred, out: _fake_write(out)
    )
    monkeypatch.setattr(
        cli.modes, "write_modes", lambda idx, minutes, pred, out, **kw: _fake_write(out)
    )
    monkeypatch.setattr(
        cli.rail_detail, "write_rail_detail",
        lambda idx, minutes, pred, routes, out_bin, out_json: (_fake_write(out_bin), _fake_write(out_json))
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
        cli.index, "write_index", lambda origins, out: index_calls.append(list(origins))
    )
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 0.0])  # "second" fails coverage

    with pytest.raises(SystemExit, match="second"):
        cli._build_all()

    assert index_calls == []  # never reached: aborted before the write
    assert len(written) == 7  # "first"'s pmtiles/hover/routes/air/modes/rail.bin/rail.json


def test_index_json_is_written_once_every_origin_succeeds(monkeypatch, tmp_path):
    """Companion to the abort test: confirms the fix does not simply delete
    the call -- a fully successful run still writes index.json, exactly once,
    with every origin.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    index_calls: list = []
    monkeypatch.setattr(
        cli.index, "write_index", lambda origins, out: index_calls.append(list(origins))
    )
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 1.0])

    cli._build_all()

    assert len(index_calls) == 1
    assert [o["slug"] for o in index_calls[0]] == ["first", "second"]
    assert len(written) == 14  # both origins' seven files each


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
                        lambda origins, out: wrote_index.append(out))

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
    assert "rail:" in out and "EXCLUDED" in out
    assert "ferries:" in out


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
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out: index_calls.append(1))

    def hung(signum, frame):
        raise TimeoutError("_build_all is hanging: the worker's gate failure never reached the parent")

    previous = signal.signal(signal.SIGALRM, hung)
    signal.alarm(30)
    try:
        with pytest.raises(SystemExit, match="second"):
            cli._build_all()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert index_calls == []
