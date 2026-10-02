"""Per-origin completion records (transport_maps.progress) through the real
build sequencing, on the stub pipeline."""

import json

import pytest

from transport_maps import cli, progress, variants

from .test_cli import _stub_pipeline

ORIGINS = {"first": {"slug": "first", "lat": 0.0, "lon": 0.0},
           "second": {"slug": "second", "lat": 1.0, "lon": 0.0}}


def _build(monkeypatch, dist, coverages=(1.0, 1.0), index_calls=None, **kw):
    monkeypatch.setattr(cli.config, "DIST", dist)
    _stub_pipeline(monkeypatch, [], coverages=list(coverages))
    calls = index_calls if index_calls is not None else []
    monkeypatch.setattr(cli.index, "write_index",
                        lambda origins, out, **k: calls.append([o["slug"] for o in origins]))
    cli._build_all(**kw)
    return calls


def _record(root, slug):
    return json.loads(progress.record_path(root, slug).read_text())


def test_a_finished_origin_records_every_file_it_wrote(monkeypatch, tmp_path):
    """The record lists the files on disk -- all of them -- with their sizes.

    Compared with what is on disk rather than with SUFFIXES, so a tenth writer
    added to `_solve_one` without a suffix in the table goes red here instead
    of producing records that vouch for nine files of ten.

    Mutations performed and reverted, each red: the `progress.finish` call
    removed (no record / still "writing"); ".over.bin" dropped from SUFFIXES.
    """
    _build(monkeypatch, tmp_path)
    for slug in ORIGINS:
        rec = _record(tmp_path, slug)
        on_disk = {p.name: p.stat().st_size for p in (tmp_path / "origins").glob(f"{slug}.*")}
        assert rec["state"] == progress.COMPLETE
        assert rec["files"] == on_disk
        assert rec["exclude"] is None and rec["inputsHash"] and rec["graphHash"]


def test_an_origin_stopped_between_two_files_is_left_writing(monkeypatch, tmp_path):
    """The failure the records exist for: a run killed after an origin's first
    file and before its last leaves the origin half one build and half the
    other, at lengths nothing else can tell apart. Its record must say so.

    Mutations performed and reverted, each red: `progress.begin` removed (the
    first build's "complete" record survives over the mixed files); `begin`
    moved below `write_pmtiles` (the record still said "complete" while the
    first file was replaced).
    """
    _build(monkeypatch, tmp_path)
    assert _record(tmp_path, "second")["state"] == progress.COMPLETE

    def crash(idx, minutes, pred, out, **kw):
        if out.name.startswith("second"):
            raise RuntimeError("killed mid-origin")
        out.write_bytes(b"x")
    seen_by_first_write: list = []

    def pmtiles(fc, out, **kw):
        seen_by_first_write.append(_record(tmp_path, out.name.split(".")[0])["state"])
        out.write_bytes(b"x")
    calls: list = []
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], coverages=[1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(cli.itinerary, "write_itinerary", crash)
    monkeypatch.setattr(cli.tiles, "write_pmtiles", pmtiles)
    with pytest.raises(RuntimeError, match="killed mid-origin"):
        cli._build_all()

    assert seen_by_first_write == [progress.WRITING] * 2, \
        "an origin's first file was replaced while its record still vouched for the old set"
    assert _record(tmp_path, "second")["state"] == progress.WRITING
    stamp = progress.Stamp(*(_record(tmp_path, "first")[k]
                             for k in ("inputsHash", "buildId", "graphHash", "exclude")))
    assert "stopped while writing" in progress.problem(tmp_path, ORIGINS["second"], stamp)
    assert progress.problem(tmp_path, ORIGINS["first"], stamp) is None
    assert calls == []


def test_a_gate_that_fails_before_any_write_leaves_the_record_alone(monkeypatch, tmp_path):
    """An origin refused by a gate has had nothing replaced: its files are the
    last build's, whole, and its record must still vouch for them.

    Mutation performed and reverted: `progress.begin` moved above the coverage
    gate -> red (the record says "writing" over untouched files).
    """
    _build(monkeypatch, tmp_path)
    before = _record(tmp_path, "second")
    with pytest.raises(SystemExit, match="second"):
        _build(monkeypatch, tmp_path, coverages=(1.0, 0.0))
    after = _record(tmp_path, "second")
    assert after["state"] == progress.COMPLETE and after["key"] == before["key"]


def test_nothing_is_published_unless_every_origin_is_recorded_complete(monkeypatch, tmp_path):
    """index.json and the variant marker are written from the records, not from
    the loop having ended.

    Mutation performed and reverted: the `unfinished` gate before publication
    removed -> red (index.json and the marker are both written).
    """
    real_finish = progress.finish

    def skip_second(root, origin, stamp):
        if origin["slug"] != "second":
            real_finish(root, origin, stamp)
    monkeypatch.setattr(cli.progress, "finish", skip_second)

    calls: list = []
    with pytest.raises(SystemExit, match="second: a build stopped while writing"):
        _build(monkeypatch, tmp_path, index_calls=calls)
    assert calls == []

    with pytest.raises(SystemExit, match="not complete for this build"):
        _build(monkeypatch, tmp_path, exclude="air")
    assert not (variants.variant_dir(tmp_path, "air") / variants.MARKER).exists()


def test_the_record_key_moves_with_every_input_it_names():
    """Each term of the key, moved alone, moves it."""
    base = progress.Stamp("in", "in-t0", "graph", None)
    origin = {"slug": "a", "lat": 1.0, "lon": 2.0}
    key = base.key(origin)
    assert progress.Stamp("in", "in-t1", "graph", None).key(origin) == key, \
        "the run's start time is not an input: a resumed run must match"
    for other in (progress.Stamp("other", "x", "graph", None),
                  progress.Stamp("in", "x", "other", None),
                  progress.Stamp("in", "x", "graph", "air")):
        assert other.key(origin) != key
    for moved in ({**origin, "lat": 1.5}, {**origin, "lon": 2.5}, {**origin, "slug": "b"}):
        assert base.key(moved) != key


def test_the_graph_digest_covers_the_edges_the_ordering_the_classes_and_the_rail_names():
    import numpy as np
    from scipy.sparse import csr_matrix

    csr = csr_matrix(np.array([[0, 1.0], [2.0, 0]]))
    args = (csr, ["p1", "p2"], np.array([1, 2]), {"stop_names": {"k": "A"}})
    base = progress.graph_hash(*args)
    assert progress.graph_hash(*args) == base
    heavier = csr.copy()
    heavier.data[0] = 1.5
    for moved in ((heavier, *args[1:]), (csr, ["p2", "p1"], *args[2:]),
                  (csr, args[1], np.array([1, 3]), args[3]),
                  (*args[:3], {"stop_names": {"k": "B"}})):
        assert progress.graph_hash(*moved) != base
