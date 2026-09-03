import argparse

import numpy as np
import pytest

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
        cells = ["dummy"]

    monkeypatch.setattr(cli.nodes, "build_index", lambda: FakeIdx())
    monkeypatch.setattr(cli.build, "build_graph", lambda idx: object())
    monkeypatch.setattr(
        cli.index, "load_origins",
        lambda: [
            {"slug": "first", "name": "First", "lat": 0.0, "lon": 0.0},
            {"slug": "second", "name": "Second", "lat": 0.0, "lon": 0.0},
        ],
    )
    monkeypatch.setattr(cli.index, "write_hover_cells", lambda idx, out: None)
    monkeypatch.setattr(cli.dijkstra, "origin_node", lambda idx, lat, lon: 0)
    monkeypatch.setattr(
        cli.dijkstra, "solve_from",
        lambda csr, source, with_predecessors=False: (np.array([1.0]), np.array([-9999])),
    )

    remaining = iter(coverages)
    monkeypatch.setattr(cli.validate, "check_coverage", lambda minutes, idx: next(remaining))
    monkeypatch.setattr(cli.validate, "check_monotonic_ground", lambda idx, minutes: None)
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
    assert len(written) == 3  # "first"'s pmtiles/hover/routes did get written


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
    assert len(written) == 6  # both origins' pmtiles/hover/routes
