"""Per-origin completion records (transport_maps.progress) through the real
build sequencing, on the stub pipeline."""

import json

import pytest

from transport_maps import cli, progress, variants

from .test_cli import _stub_pipeline, forks_a_threaded_process

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


# --- A6e: build-all --skip-existing ------------------------------------------

def _resume(monkeypatch, dist, coverages=(1.0, 1.0), identity=None, csr=None, **kw):
    """One stub run, returning (origins solved, index.json calls)."""
    from scipy.sparse import csr_matrix

    monkeypatch.setattr(cli.config, "DIST", dist)
    _stub_pipeline(monkeypatch, [], coverages=list(coverages))
    if identity is not None:
        monkeypatch.setattr(cli.index, "build_identity", lambda started=None: dict(identity))
    if csr is not None:
        monkeypatch.setattr(cli.build, "build_graph", lambda idx, **k: csr_matrix(csr))
    calls: list = []
    monkeypatch.setattr(cli.index, "write_index",
                        lambda origins, out, **k: calls.append(
                            ([o["slug"] for o in origins],
                             {n: v for n, v in k.items() if n != "identity"},
                             k["identity"]["inputsHash"])))
    solved: list = []
    real = cli._solve_one
    monkeypatch.setattr(cli, "_solve_one",
                        lambda o, *a: (solved.append(o["slug"]), real(o, *a))[1])
    cli._build_all(**kw)
    return solved, calls


IDENT = {"inputsHash": "in-1", "buildId": "in-1-t0", "builtAt": "t0", "gitHead": "h"}


def test_a_resumed_build_skips_only_what_is_complete_for_the_current_inputs(monkeypatch, tmp_path):
    """Skipped only under the same inputsHash AND the same graph; without the
    flag nothing is skipped at all.

    Mutations performed and reverted, each red: `_still_to_build` returning
    every origin (nothing skipped); returning none (a moved inputsHash still
    skipped); the stamp built from a constant graph digest instead of
    `progress.graph_hash(csr, ...)` (a changed graph still skipped).
    """
    solved, _ = _resume(monkeypatch, tmp_path, identity=IDENT)
    assert solved == ["first", "second"]
    solved, calls = _resume(monkeypatch, tmp_path, identity=IDENT, skip_existing=True)
    assert solved == [] and calls[0][0] == ["first", "second"]
    solved, _ = _resume(monkeypatch, tmp_path, identity=IDENT)
    assert solved == ["first", "second"], "without --skip-existing every origin is built"

    solved, _ = _resume(monkeypatch, tmp_path, identity=IDENT, skip_existing=True,
                        csr=[[0.0, 1.0], [1.0, 0.0]])
    assert solved == ["first", "second"], "skipped over another graph"
    moved = {**IDENT, "inputsHash": "in-2", "buildId": "in-2-t1"}
    solved, _ = _resume(monkeypatch, tmp_path, identity=moved, skip_existing=True,
                        csr=[[0.0, 1.0], [1.0, 0.0]])
    assert solved == ["first", "second"], "skipped under another inputsHash"


def test_a_missing_resized_or_half_written_origin_is_rebuilt(monkeypatch, tmp_path):
    """Mutation performed and reverted: `files_problem` returning None (the
    file checks skipped) -> red."""
    _resume(monkeypatch, tmp_path, identity=IDENT)
    (tmp_path / "origins" / "first.air.bin").unlink()
    solved, _ = _resume(monkeypatch, tmp_path, identity=IDENT, skip_existing=True)
    assert solved == ["first"]
    p = tmp_path / "origins" / "second.json"
    p.write_bytes(p.read_bytes() + b" ")
    solved, _ = _resume(monkeypatch, tmp_path, identity=IDENT, skip_existing=True)
    assert solved == ["second"]
    rec = _record(tmp_path, "first")
    progress.record_path(tmp_path, "first").write_text(json.dumps({**rec, "state": "writing"}))
    solved, _ = _resume(monkeypatch, tmp_path, identity=IDENT, skip_existing=True)
    assert solved == ["first"]


def test_a_resumed_run_publishes_what_a_full_run_publishes(monkeypatch, tmp_path):
    """index.json from a run that skipped everything is the one a run that
    built everything writes: same origins, same counts, same inputs."""
    _, full = _resume(monkeypatch, tmp_path, identity=IDENT)
    solved, resumed = _resume(monkeypatch, tmp_path, identity=IDENT, skip_existing=True)
    assert solved == [] and resumed == full


def test_a_variant_that_died_is_resumed_and_offered_again(monkeypatch, tmp_path):
    """The 2026-09-28 case: a variant build dies part way. The marker went at
    the start and must come back only when every origin is complete -- from
    the resumed run, which builds only what the dead one did not finish.

    Mutation performed and reverted: the withdraw at the start of a full
    variant run skipped when --skip-existing is given -> red (the old marker
    survives the second failed run).
    """
    root = variants.variant_dir(tmp_path, "air")
    variants.write_marker(root, "air", ["first", "second"], {"inputsHash": "older"})
    with pytest.raises(SystemExit, match="second"):
        _resume(monkeypatch, tmp_path, coverages=(1.0, 0.0), identity=IDENT, exclude="air")
    assert not (root / variants.MARKER).exists()
    variants.write_marker(root, "air", ["first", "second"], {"inputsHash": "older"})
    with pytest.raises(SystemExit, match="second"):
        _resume(monkeypatch, tmp_path, coverages=(1.0, 0.0), identity=IDENT, exclude="air",
                skip_existing=True)
    assert not (root / variants.MARKER).exists(), "a resumed run that failed left it offered"

    solved, calls = _resume(monkeypatch, tmp_path, identity=IDENT, exclude="air",
                            skip_existing=True)
    assert solved == ["second"] and calls == []
    marker = json.loads((root / variants.MARKER).read_text())
    assert marker["origins"] == ["first", "second"]
    assert marker["identity"]["inputsHash"] == "in-1"
    assert not (tmp_path / "origins").exists(), "a variant resumed into the full set's tree"


@pytest.mark.parametrize("partial", [{"only": ["first"]}, {"limit": 1}])
def test_a_partial_resumed_run_still_never_publishes(monkeypatch, tmp_path, partial):
    _resume(monkeypatch, tmp_path, identity=IDENT)
    progress.record_path(tmp_path, "first").unlink()
    solved, calls = _resume(monkeypatch, tmp_path, identity=IDENT, skip_existing=True, **partial)
    assert solved == ["first"] and calls == []


@forks_a_threaded_process   # W1: why this is safe is beside its definition
def test_forked_workers_report_each_origin_as_it_finishes(monkeypatch, tmp_path, capsys):
    """imap_unordered: a slow first origin does not hold back the row of one
    that finished behind it.

    Mutation performed and reverted: `pool.imap` back -> red ("second" waits
    for "first").
    """
    import signal
    import time

    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    monkeypatch.setattr(cli, "_worker_count", lambda n_origins: 2)
    _stub_pipeline(monkeypatch, [], coverages=[1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda *a, **k: None)

    def slow_first(minutes, idx, reachable=None):
        if int(minutes[0]) == 0:
            time.sleep(1.5)
        return 1.0
    monkeypatch.setattr(cli.validate, "check_coverage", slow_first)

    def hung(signum, frame):
        raise TimeoutError("the forked build hung")
    previous = signal.signal(signal.SIGALRM, hung)
    signal.alarm(15)
    try:
        cli._build_all()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    rows = [ln.split()[0] for ln in capsys.readouterr().out.splitlines()
            if ln.split()[:1] in (["first"], ["second"])]
    assert rows == ["second", "first"], rows


def test_the_graph_digest_ignores_edge_order_within_a_row_and_set_order():
    """Rebuild 28's two starts on h200 built the same graph and hashed it two
    ways, so --skip-existing resumed nothing. Row order and set order are
    artefacts of assembly, not content.

    Mutations performed and reverted, each -> red: drop both
    `sum_duplicates()` and `sort_indices()` (either alone is enough, since
    sum_duplicates sorts too -- dropping only one stays green, equivalently);
    pickle rail_tables as given instead of `_canonical`.
    """
    import subprocess
    import sys

    import scipy.sparse as sp

    from transport_maps import progress

    rows, cols, w = [0, 0, 1, 2], [2, 1, 0, 1], [5.0, 3.0, 2.0, 7.0]
    a = sp.csr_matrix((w, (rows, cols)), shape=(3, 3))
    order = [1, 0, 3, 2]
    b = sp.csr_matrix(([w[i] for i in order], ([rows[i] for i in order], [cols[i] for i in order])),
                      shape=(3, 3))
    # Unsort b's row 0 by hand: coo->csr would otherwise sort it for us.
    b.indices[:2], b.data[:2] = b.indices[:2][::-1].copy(), b.data[:2][::-1].copy()
    assert not b.has_sorted_indices or list(b.indices[:2]) != list(a.indices[:2])
    tables = {"stations": {"b", "a", "c"}}
    assert progress.graph_hash(a, ["p"], [0, 1, 2], tables) == \
        progress.graph_hash(b, ["p"], [0, 1, 2], tables)
    # The set's order depends on PYTHONHASHSEED; two seeds must agree.
    code = ("import scipy.sparse as sp; from transport_maps import progress; "
            "m = sp.csr_matrix(([1.0], ([0], [1])), shape=(2, 2)); "
            "print(progress.graph_hash(m, ['p'], [0, 0], {'s': set('abcdefghij')}))")
    seen = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={**__import__('os').environ, "PYTHONHASHSEED": seed},
                           check=True).stdout.strip() for seed in ("1", "2", "3")}
    assert len(seen) == 1, seen


def test_an_operator_can_trust_records_from_other_digests(monkeypatch, tmp_path):
    """Only with TRANSPORT_MAPS_RESUME_TRUST_RECORDS=1, and only a record for
    the same origin and variant (its key must recompute from its own digests).

    Mutations performed and reverted, each -> red: ignore the variable; skip
    the key recomputation (accept any record).
    """
    from transport_maps import progress

    origin = {"slug": "x", "lat": 1.0, "lon": 2.0}
    old = progress.Stamp("code1", "b1", "graphA", None)
    new = progress.Stamp("code1", "b2", "graphB", None)
    other_code = progress.Stamp("code2", "b3", "graphB", None)
    rec = {"key": old.key(origin), "inputsHash": "code1", "graphHash": "graphA"}
    monkeypatch.delenv(progress.TRUST_RECORDS_ENV, raising=False)
    assert not progress._accepted_other_graph(rec, origin, new)
    monkeypatch.setenv(progress.TRUST_RECORDS_ENV, "1")
    assert progress._accepted_other_graph(rec, origin, new)
    assert progress._accepted_other_graph(rec, origin, other_code)
    # Another origin's record, or another variant's, is never this one's.
    assert not progress._accepted_other_graph(rec, {**origin, "slug": "y"}, new)
    variant = progress.Stamp("code1", "b2", "graphB", "air")
    assert not progress._accepted_other_graph(rec, origin, variant)
