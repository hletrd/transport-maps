import argparse
from typing import ClassVar

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from transport_maps import cli
from transport_maps.cli import _slug


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
    return value for each in turn. `written` records every emitted file path.
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
            {"slug": "second", "name": "Second", "lat": 0.0, "lon": 0.0},
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
    monkeypatch.setattr(cli.roads, "cell_class", lambda cells: np.array([1]))
    monkeypatch.setattr(cli.dijkstra, "origin_node", lambda idx, lat, lon: 0)
    monkeypatch.setattr(
        cli.dijkstra, "solve_from",
        lambda csr, source, with_predecessors=False: (np.array([1.0]), np.array([-9999])),
    )

    remaining = iter(coverages)
    monkeypatch.setattr(cli.validate, "check_coverage", lambda minutes, idx: next(remaining))
    monkeypatch.setattr(
        cli.validate, "check_monotonic_ground", lambda idx, minutes, speeds, **kw: None
    )
    monkeypatch.setattr(cli.bands, "band_feature_collection", lambda idx, minutes: {"features": []})
    monkeypatch.setattr(cli.validate, "check_bands_disjoint", lambda fc: None)

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
    assert len(written) == 5  # "first"'s pmtiles/hover/routes/air/modes


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
    assert len(written) == 10  # both origins' pmtiles/hover/routes/air/modes


def test_a_limited_build_does_not_rewrite_index_json(monkeypatch, tmp_path):
    """--limit is a smoke test, not a deploy.

    Rewriting index.json from a partial run leaves dist/ advertising only the
    origins that run happened to build, which looks exactly like a real build
    until the live site drops to one city.
    """
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    # one origin for the limited run, then two for the full one
    _stub_pipeline(monkeypatch, written, [1.0, 1.0, 1.0])
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
