"""`transport-maps reindex` rewrites index.json from artifacts already on disk.

The command exists because index.json is written by the build's parent process
at the END of the run, from the emit.index module that parent imported at the
START. A build that outlives an emitter change publishes a stale index for
artifacts that are not stale, and the stale index turns off the page's
mixed-build guard, its channel-order guard and its rail-detail fetch.
"""

import json

import pytest

from transport_maps import cli, config
from transport_maps.emit import modes

N_CELLS = 5
WIDTHS = {".bin": 2, ".air.bin": 2, ".modes.bin": 2 * len(modes.CHANNELS)}


def _origin(slug, lat=0.0, lon=0.0):
    return {"slug": slug, "name": slug.title(), "lat": lat, "lon": lon}


def _artifacts(dist, slug, *, cells=N_CELLS, rail=False, short=None):
    """Write one origin's file set. `short` names a suffix to truncate."""
    out = dist / "origins"
    out.mkdir(parents=True, exist_ok=True)
    for suffix, width in WIDTHS.items():
        n = cells - 1 if short == suffix else cells
        (out / f"{slug}{suffix}").write_bytes(b"\0" * (n * width))
    (out / f"{slug}.json").write_text('{"offsets":{}}')
    (out / f"{slug}.pmtiles").write_bytes(b"PMTiles" + b"\0" * 120)
    if rail:
        (out / f"{slug}.rail.bin").write_bytes(b"\0" * (cells * 4))
        (out / f"{slug}.rail.json").write_text("{}")


@pytest.fixture
def dist(tmp_path, monkeypatch):
    d = tmp_path / "dist"
    (d / "origins").mkdir(parents=True)
    (d / "hover_cells.bin").write_bytes(b"\0" * (N_CELLS * 8))
    # No real build may interfere, and this machine may genuinely be running
    # one: the guard itself is tested separately.
    monkeypatch.setattr(cli, "_other_builds", lambda **k: [])
    return d


def _reindex(dist, origins, monkeypatch):
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: origins)
    cli._reindex(dist)
    return json.loads((dist / "index.json").read_text())


def test_reindex_stamps_the_keys_a_long_build_publishes_without(dist, monkeypatch):
    """The six fields a stale emitter omits are exactly what this restores."""
    _artifacts(dist, "seoul", rail=True)
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)

    assert idx["hoverCellCount"] == N_CELLS, "the page's mixed-build guard needs this"
    assert idx["modeChannels"] == list(modes.CHANNELS), "the page re-types the order without it"
    assert idx["railDetail"] is True, "false here means the shipped .rail.* is never fetched"
    assert idx["graph"]["rail"] is True
    assert idx["builtAt"] and idx["reindexedAt"]
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]


def test_an_origin_whose_array_is_short_is_not_listed(dist, monkeypatch):
    """Listing a short array is the blank-globe failure the command prevents."""
    _artifacts(dist, "seoul")
    _artifacts(dist, "tokyo", short=".modes.bin")
    idx = _reindex(dist, [_origin("seoul"), _origin("tokyo")], monkeypatch)
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]


def test_an_origin_missing_a_file_is_not_listed(dist, monkeypatch):
    _artifacts(dist, "seoul")
    _artifacts(dist, "tokyo")
    (dist / "origins" / "tokyo.air.bin").unlink()
    idx = _reindex(dist, [_origin("seoul"), _origin("tokyo")], monkeypatch)
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]


def test_rail_detail_is_false_when_no_origin_has_rail_files(dist, monkeypatch):
    """The name of this test is railDetail, and railDetail is what it asserts.

    It used to assert graph.rail instead, while railDetail was hard-coded True
    in the emitter with no parameter to write anything else. So reindex printed
    'rail detail absent' and published 'railDetail': true in the same breath:
    two 404s per origin switch on the page, which browser_verify.sh fails the
    deploy for, and one check_dist problem per origin naming reindex as the
    remedy for the state reindex had just created.
    """
    _artifacts(dist, "seoul", rail=False)
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["railDetail"] is False, (
        "advertising rail detail over a dist/ that has none is two 404s per origin")
    assert idx["graph"]["rail"] is False


def test_rail_detail_follows_the_files_not_the_emitter_version(dist, monkeypatch):
    """One origin with rail files and one without: the flag follows the dist/."""
    _artifacts(dist, "seoul", rail=True)
    _artifacts(dist, "tokyo", rail=False)
    idx = _reindex(dist, [_origin("seoul"), _origin("tokyo")], monkeypatch)
    assert idx["railDetail"] is True


def test_identity_is_carried_forward_not_restamped(dist, monkeypatch):
    """Stamping today's checkout would assert it produced files it did not."""
    _artifacts(dist, "seoul")
    (dist / "index.json").write_text(json.dumps({
        "inputsHash": "deadbeef", "buildId": "deadbeef-20260910T042333Z",
        "builtAt": "2026-09-10T04:23:33+00:00", "gitHead": "abc1234",
        "origins": [], "graph": {"ferry": True}}))
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["inputsHash"] == "deadbeef"
    assert idx["buildId"] == "deadbeef-20260910T042333Z"
    assert idx["builtAt"] == "2026-09-10T04:23:33+00:00"
    assert idx["gitHead"] == "abc1234", "the commit that built the files, not this checkout's"
    assert idx["graph"]["ferry"] is True, "what the artifacts cannot show is carried, not dropped"
    assert idx["reindexedAt"] != idx["builtAt"]


def test_built_at_falls_back_to_the_hover_file_the_build_wrote_first(dist, monkeypatch):
    """hover_cells.bin is written before the first origin, so its mtime is the start."""
    import os
    os.utime(dist / "hover_cells.bin", (1_757_000_000, 1_757_000_000))
    _artifacts(dist, "seoul")
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["builtAt"].startswith("2025-09-")


def test_reindex_refuses_while_another_build_is_running(dist, monkeypatch):
    _artifacts(dist, "seoul")
    monkeypatch.setattr(cli, "_other_builds",
                        lambda **k: [4143, 4144] if k.get("min_cpu") else [4143, 4144, 9001])
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="4143"):
        cli._reindex(dist)
    assert not (dist / "index.json").exists(), "a refusal must not leave a partial index"
    assert not (dist / cli.LOCK_NAME).exists(), "the lock is released on the refusal path"


def test_reindex_refuses_a_dist_with_no_hover_cells(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_other_builds", lambda **k: [])
    with pytest.raises(SystemExit, match="hover_cells.bin missing"):
        cli._reindex(tmp_path / "empty")


def test_reindex_refuses_when_no_origin_is_complete(dist, monkeypatch):
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="complete file set"):
        cli._reindex(dist)


# --- U1: the CPU filter on _other_builds -----------------------------------
#
# reindex exists to repair the index a long build publishes. Without a CPU
# filter it refuses on any matching process, including the orphans of a build
# killed days earlier -- which is the state this machine was in when the filter
# was written: `ps` listed seventeen candidates and only five were working.
# The operator is then stranded between two gates that disagree, because
# deploy_verify.sh has filtered by CPU since 6d4ac0f and check_dist names
# reindex as the remedy for the index reindex is refusing to write.

PS_LINES = (
    "  4143  98.4 /path/.venv/bin/python -m transport_maps.cli build-all\n"
    " 12633   0.0 /path/.venv/bin/python -m transport_maps.cli build-all\n"
    " 12634   0.0 /path/.venv/bin/python -m transport_maps.cli build-all\n"
    " 55555  12.0 /usr/bin/vim notes-about-build-all.txt\n"
)


def _fake_ps(monkeypatch, stdout=PS_LINES):
    import subprocess as sp

    def run(cmd, **kw):
        assert cmd[:2] == ["ps", "-axo"], cmd
        assert "pcpu=" in cmd[2], "the filter needs ps to report CPU"
        return sp.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(cli.subprocess, "run", run)


def test_other_builds_without_a_floor_reports_the_orphans_too(monkeypatch):
    """A build wants every match: an idle worker still holds graph memory."""
    _fake_ps(monkeypatch)
    assert cli._other_builds() == [4143, 12633, 12634]


def test_other_builds_above_the_busy_floor_drops_a_killed_builds_orphans(monkeypatch):
    """The whole point: 0.0 % processes are corpses and never write index.json."""
    _fake_ps(monkeypatch)
    assert cli._other_builds(min_cpu=cli.BUSY_CPU_PERCENT) == [4143]


def test_a_process_that_merely_mentions_build_all_is_not_a_build(monkeypatch):
    _fake_ps(monkeypatch)
    assert 55555 not in cli._other_builds()


def test_an_unreadable_cpu_column_counts_as_busy(monkeypatch):
    """Refusing is the safe direction when ps cannot be parsed."""
    _fake_ps(monkeypatch, " 4143  ?.? /path/python -m transport_maps.cli build-all\n")
    assert cli._other_builds(min_cpu=cli.BUSY_CPU_PERCENT) == [4143]


def test_reindex_runs_past_a_killed_builds_orphans(dist, monkeypatch, caplog):
    """The failure U1 fixes: reindex refusing because of yesterday's corpses.

    Deliberately NOT patching _other_builds -- patching ps is what makes this
    exercise the filter rather than the stub.
    """
    _artifacts(dist, "seoul")
    monkeypatch.undo()  # drop the fixture's _other_builds stub
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    _fake_ps(monkeypatch, " 12633   0.0 /p/python -m transport_maps.cli build-all\n"
                          " 12634   0.0 /p/python -m transport_maps.cli build-all\n")
    cli._reindex(dist)
    idx = json.loads((dist / "index.json").read_text())
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]
    assert "12633" in caplog.text and "Reap" in caplog.text, (
        "the ignored orphans must be named, not silently dropped")


def test_reindex_still_refuses_a_build_that_is_actually_working(dist, monkeypatch):
    _artifacts(dist, "seoul")
    monkeypatch.undo()
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    _fake_ps(monkeypatch, " 4143  98.4 /p/python -m transport_maps.cli build-all\n")
    with pytest.raises(SystemExit, match="4143"):
        cli._reindex(dist)
    assert not (dist / "index.json").exists()
    assert not (dist / cli.LOCK_NAME).exists()


# --- U3: index fields that describe the artifacts, not the checkout ---------
#
# reindex is fastidious with identity -- "carried forward, never invented" --
# and then write_index derived bandEdgesMin, solveRes, modeChannels and
# modeDetail from today's code and today's calibration.toml. The in-flight
# 553-origin build read calibration.toml at ~04:28 and the file was rewritten at
# 05:34:33; T20 exists because of that gap. reindex had the same gap.

def _previous(dist, **extra):
    from transport_maps import config
    (dist / "index.json").write_text(json.dumps({
        "bandEdgesMin": list(config.BAND_EDGES_MIN),
        "solveRes": config.SOLVE_RES,
        "modeChannels": list(modes.CHANNELS),
        **extra}))


def test_mode_prose_is_carried_forward_not_resampled(dist, monkeypatch):
    """The route panel's mode tooltips are figures a visitor reads."""
    _artifacts(dist, "seoul")
    _previous(dist, modeDetail={"motorway": "Motorways, fitted at 90 km/h as of the build"})
    called = []
    monkeypatch.setattr(cli.index, "mode_detail",
                        lambda *a, **k: called.append(1) or {"motorway": "today's value"})
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["modeDetail"]["motorway"].endswith("as of the build"), (
        "reindex must not re-read calibration.toml for prose describing older artifacts")
    assert not called, "mode_detail() must not be called when the previous index has the prose"


def test_a_previous_index_without_mode_prose_says_so(dist, monkeypatch, caplog):
    _artifacts(dist, "seoul")
    _previous(dist)
    _reindex(dist, [_origin("seoul")], monkeypatch)
    assert "sampled from calibration.toml NOW" in caplog.text


def test_reindex_refuses_when_the_band_edges_have_moved(dist, monkeypatch):
    """A new legend over old tiles is the failure this prevents."""
    _artifacts(dist, "seoul")
    _previous(dist, bandEdgesMin=[1, 2, 3])
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="bandEdgesMin"):
        cli._reindex(dist)
    assert json.loads((dist / "index.json").read_text())["bandEdgesMin"] == [1, 2, 3], (
        "the refusal must leave the existing index untouched")


def test_reindex_refuses_when_the_channel_order_has_moved(dist, monkeypatch):
    _artifacts(dist, "seoul")
    _previous(dist, modeChannels=["road", "rail"])
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="modeChannels"):
        cli._reindex(dist)


def test_reindex_refuses_when_the_solve_resolution_has_moved(dist, monkeypatch):
    """Exactly the res-5 -> res-6 change this build is making."""
    _artifacts(dist, "seoul")
    _previous(dist, solveRes=5)
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="solveRes"):
        cli._reindex(dist)


def test_an_index_with_none_of_those_fields_still_reindexes(dist, monkeypatch):
    """The 04:23 emitter wrote bandEdgesMin but a truly bare index must work."""
    _artifacts(dist, "seoul")
    (dist / "index.json").write_text('{"origins":[]}')
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]


def test_reindex_refuses_when_the_hover_resolution_has_moved(dist, monkeypatch):
    """The omission that mattered most.

    hoverRes is the resolution of hover_cells.bin, which the page
    binary-searches by cell id (app.js: cellIndex). Republish an index whose
    hoverRes has moved and every lookup misses, so every land cell reads
    "Open water." -- and nothing else sees it: check_dist compares
    hoverCellCount against the file's length, and the page's own guard
    compares the same two, so a drift that keeps the COUNT the same passes
    both.

    Mutation: drop "hoverRes" from cli._CURRENT_INDEX_CONSTANTS.
    """
    _artifacts(dist, "seoul")
    _previous(dist, hoverRes=config.HOVER_RES + 1)
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="hoverRes"):
        cli._reindex(dist)


def test_reindex_refuses_when_the_unreachable_sentinel_has_moved(dist, monkeypatch):
    """Mutation: drop "unreachable" from cli._CURRENT_INDEX_CONSTANTS."""
    _artifacts(dist, "seoul")
    _previous(dist, unreachable=config.UNREACHABLE - 1)
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="unreachable"):
        cli._reindex(dist)


def test_reindex_refuses_when_the_contract_version_has_moved(dist, monkeypatch):
    """J1b(b). `contractVersion` names the layout the arrays were written in.
    Stamping today's number over a dist/ built under another one tells the
    page that old arrays have the new layout, which is the one thing the
    number exists to prevent.

    Mutation: drop "contractVersion" from cli._CURRENT_INDEX_CONSTANTS.
    """
    _artifacts(dist, "seoul")
    _previous(dist, contractVersion=cli.index.CONTRACT_VERSION - 1)
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="contractVersion"):
        cli._reindex(dist)
    assert json.loads((dist / "index.json").read_text())["contractVersion"] == (
        cli.index.CONTRACT_VERSION - 1), "the refusal must leave the existing index untouched"


def test_an_index_from_before_the_contract_version_still_reindexes(dist, monkeypatch):
    """An absent key passes, as for every other frozen key: an index.json from
    before the field existed is the one every shipped dist/ has today, and
    refusing it would make reindex unusable on exactly the builds it serves."""
    _artifacts(dist, "seoul")
    _previous(dist)
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["contractVersion"] == cli.index.CONTRACT_VERSION


def test_the_contract_version_refusal_reads_todays_emitter(monkeypatch):
    """A lambda returning a frozen 2 would pass both tests above until the
    first bump, and then refuse every dist/ written by the new code.

    Mutation: `"contractVersion": lambda: 2` in cli._CURRENT_INDEX_CONSTANTS.
    """
    current = cli._CURRENT_INDEX_CONSTANTS["contractVersion"]
    before = current()
    monkeypatch.setattr(cli.index, "CONTRACT_VERSION", before + 1)
    assert current() == before + 1


def test_every_constant_write_index_derives_is_in_the_refusal_set():
    """The refusal set was three of five, and stayed three of five while
    write_index grew. Derive the question from the artifact instead of
    re-typing the answer: any scalar field index.json carries that comes from
    `config` and is not carried forward must be refused on drift.

    Mutation: remove any entry from _CURRENT_INDEX_CONSTANTS.
    """
    governed = _config_derived_index_keys()
    assert governed, "no config-derived key found in write_index; re-derive this test"
    assert governed <= set(cli._CURRENT_INDEX_CONSTANTS), (
        "a constant index.json publishes is not covered by the drift refusal: "
        f"{governed - set(cli._CURRENT_INDEX_CONSTANTS)}")
    # ...and each really does read today's config, not a frozen copy.
    #
    # `assert current() is not None` could not show that: a lambda returning a
    # hard-coded 4 is not None either, and freezing "hoverRes" that way left
    # both guards in this file green. Monkeypatch the config attribute the
    # lambda names and require the lambda's answer to MOVE with it -- which is
    # the only thing "reads today's config" can mean.
    import transport_maps.config as cfg
    names = {"bandEdgesMin": "BAND_EDGES_MIN", "solveRes": "SOLVE_RES",
             "hoverRes": "HOVER_RES", "fineRes": "FINE_RES",
             "unreachable": "UNREACHABLE", "readingRes": "READING_RES",
             "readingParentRes": "READING_PARENT_RES",
             "readingSlots": "READING_SLOTS"}
    checked = 0
    for key, current in cli._CURRENT_INDEX_CONSTANTS.items():
        before = current()
        assert before is not None, key
        attr = names.get(key)
        if attr is None or not isinstance(getattr(cfg, attr, None), int):
            continue                       # not a plain int; covered by `governed`
        original = getattr(cfg, attr)
        try:
            setattr(cfg, attr, original + 1)
            assert current() != before, (
                f"_CURRENT_INDEX_CONSTANTS[{key!r}] does not read config.{attr}; "
                "a frozen lambda makes the drift refusal blind to exactly the "
                "constant it is named for")
            checked += 1
        finally:
            setattr(cfg, attr, original)
    assert checked >= 4, (
        f"only {checked} constants were actually exercised against config; "
        "the mapping above has gone stale")


def test_the_inputs_hash_covers_the_unreachable_sentinel(monkeypatch):
    """Two builds differing only in the sentinel every uint16 array is written
    with produced identical inputsHash AND identical buildId, so the field that
    exists to tell artifacts apart could not tell those two apart.

    Mutation: remove config.UNREACHABLE from index.build_identity's params_hash.
    """
    before = cli.index.build_identity()["inputsHash"]
    monkeypatch.setattr(config, "UNREACHABLE", config.UNREACHABLE - 1)
    assert cli.index.build_identity()["inputsHash"] != before


# --- C6-20: the refusal set, derived rather than re-typed --------------------

#: The modules whose values are "the code's constants" for this purpose: a
#: payload field computed from either is frozen into the artifact at build time
#: and must be refused when it has since moved. `mode_detail()` is deliberately
#: NOT one of them -- it reads calibration.toml and reindex carries it forward
#: by design (U3), which is recorded as AA9 in plan/deferred.md.
_CONSTANT_MODULES = {"config", "modes"}


def _config_derived_index_keys() -> set[str]:
    """Parse `write_index` and return the payload keys computed from constants.

    The test this serves said in its own docstring that it derives the question
    from the artifact "instead of re-typing the answer", and then re-typed the
    answer: a hard-coded set of six. Growing `write_index` by one
    config-derived scalar left 201 tests green -- the exact regression the test
    is named for. This reads the source.
    """
    import ast

    src = (config.ROOT / "src" / "transport_maps" / "emit" / "index.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "write_index")
    payload = next(
        node.value for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "payload" for t in node.targets))
    assert isinstance(payload, ast.Dict), "write_index no longer builds a dict literal"

    # emit/index.py's own module-level integer constants are the code's
    # constants too. CONTRACT_VERSION is one, and it was the key this parse
    # could not see: it is a bare name, not `config.X`, so the field sat
    # outside the refusal set with this test green (J1b).
    module_ints = {
        t.id for node in ast.parse(src).body if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant) and type(node.value.value) is int
        for t in node.targets if isinstance(t, ast.Name)}
    assert "CONTRACT_VERSION" in module_ints, "re-derive: the version constant moved"

    derived = set()
    for key, value in zip(payload.keys, payload.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        names = {n.value.id for n in ast.walk(value)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        bare = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
        if names & _CONSTANT_MODULES or bare & module_ints:
            derived.add(key.value)
    return derived
