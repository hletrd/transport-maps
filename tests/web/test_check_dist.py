"""The deploy gate must refuse every kind of inconsistent dist/ it exists for."""

import importlib.util
import json
import struct

import pytest

from transport_maps import config
from transport_maps.emit.index import ATTRIBUTION
from transport_maps.emit.modes import CHANNELS


@pytest.fixture(scope="module")
def check_dist():
    spec = importlib.util.spec_from_file_location("check_dist", config.ROOT / "scripts" / "check_dist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N_CELLS = 3


def _pmtiles(path, size=4096, metadata=b'{"name":"water"}', gzipped=False):
    if gzipped:
        import gzip
        metadata = gzip.compress(metadata)
    head = bytearray(127)
    head[:7] = b"PMTiles"
    head[7] = 3
    # root dir at 127 (len 100), metadata at 227, leaves after it (len 0), then tiles
    mlen = len(metadata)
    struct.pack_into("<QQQQQQQQ", head, 8, 127, 100, 227, mlen,
                     227 + mlen, 0, 227 + mlen, size - 227 - mlen)
    body = bytearray(b"\0" * (size - 127))
    body[227 - 127:227 - 127 + mlen] = metadata
    path.write_bytes(bytes(head) + bytes(body))


def _good_dist(tmp_path, slugs=("seoul",), rail=True):
    d = tmp_path / "dist"
    (d / "origins").mkdir(parents=True)
    (d / "hover_cells.bin").write_bytes(b"\0" * 8 * N_CELLS)
    for s in slugs:
        (d / "origins" / f"{s}.bin").write_bytes(b"\0" * 2 * N_CELLS)
        (d / "origins" / f"{s}.air.bin").write_bytes(b"\0" * 2 * N_CELLS)
        (d / "origins" / f"{s}.modes.bin").write_bytes(b"\0" * 2 * len(CHANNELS) * N_CELLS)
        # Real offsets: an empty object used to pass, and the page then lost
        # its route panel with no error, so a "good" dist must carry them.
        (d / "origins" / f"{s}.json").write_text(json.dumps(
            {"offsets": {"airports": 1000, "stations": 1200}, "nodes": []}))
        _pmtiles(d / "origins" / f"{s}.pmtiles")
        if rail:
            (d / "origins" / f"{s}.rail.bin").write_bytes(b"\0" * 2 * N_CELLS)
            (d / "origins" / f"{s}.rail.json").write_text('{"fields":[],"stations":[]}')
    for extra in ("places.json", "airports.json", "borders.json"):
        (d / extra).write_text("{}")
    _pmtiles(d / "water.pmtiles")
    (d / "index.json").write_text(json.dumps({
        "origins": [{"slug": s, "name": s, "lat": 0, "lon": 0} for s in slugs],
        "bandEdgesMin": [30, 60], "railDetail": rail, "hoverCellCount": N_CELLS,
        "modeChannels": list(CHANNELS),
        # Every source the pipeline consumes, because crediting them is a
        # licence obligation and a "good" dist/ is one that meets it.
        "attribution": [dict(a) for a in ATTRIBUTION],
    }))
    return d


def test_a_consistent_dist_passes(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    assert check_dist.check_dist(d, [{"slug": "seoul"}]) == []


def test_a_truncated_array_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    p = d / "origins" / "seoul.bin"
    p.write_bytes(p.read_bytes()[:-2])
    assert any("seoul.bin has 2 entries" in m for m in check_dist.check_dist(d))


def test_the_modes_width_comes_from_the_emitter(check_dist, tmp_path):
    """A seventh channel must not drift past the gate: the expected width is
    2 * len(CHANNELS), passed in, never a literal 12."""
    d = _good_dist(tmp_path)
    p = d / "origins" / "seoul.modes.bin"
    p.write_bytes(b"\0" * 2 * (len(CHANNELS) + 1) * N_CELLS)
    assert any("seoul.modes.bin" in m for m in check_dist.check_dist(d))
    idx = json.loads((d / "index.json").read_text())
    idx["modeChannels"].append("hovercraft")
    (d / "index.json").write_text(json.dumps(idx))
    assert check_dist.check_dist(d, n_channels=len(CHANNELS) + 1) == []


def test_rail_files_must_ship_together_and_when_advertised(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    (d / "origins" / "seoul.rail.json").unlink()
    problems = check_dist.check_dist(d)
    assert any("ship together" in m for m in problems)
    (d / "origins" / "seoul.rail.bin").unlink()
    assert any("advertises railDetail" in m for m in check_dist.check_dist(d))


def test_a_listed_origin_with_no_files_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path, slugs=("seoul", "tokyo"))
    for p in (d / "origins").glob("tokyo.*"):
        p.unlink()
    problems = check_dist.check_dist(d)
    assert any("tokyo.bin missing" in m for m in problems) and any("tokyo.pmtiles missing" in m for m in problems)


def test_index_json_must_list_exactly_the_origins_of_origins_toml(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    problems = check_dist.check_dist(d, [{"slug": "seoul"}, {"slug": "tokyo"}])
    assert any("origins.toml has 2" in m for m in problems)


def test_a_stray_journal_or_temp_file_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    (d / "origins" / "las-vegas.pmtiles-journal").write_bytes(b"x")
    (d / ".index.json.abcd.tmp").write_bytes(b"x")
    problems = check_dist.check_dist(d)
    assert sum("stray file" in m for m in problems) == 2


def test_a_held_build_lock_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    (d / ".build.lock").write_text("1 now\n")
    assert any(".build.lock present" in m for m in check_dist.check_dist(d))


def test_a_truncated_pmtiles_is_refused_by_its_header(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    p = d / "origins" / "seoul.pmtiles"
    p.write_bytes(p.read_bytes()[:2000])
    assert any("runs past the end" in m for m in check_dist.check_dist(d))
    p.write_bytes(b"not an archive at all" + b"\0" * 200)
    assert any("PMTiles magic" in m for m in check_dist.check_dist(d))


def test_the_hover_count_in_index_json_must_match_the_file(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    idx["hoverCellCount"] = N_CELLS + 1
    (d / "index.json").write_text(json.dumps(idx))
    assert any("hoverCellCount" in m for m in check_dist.check_dist(d))


def test_a_corrupt_routes_json_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    (d / "origins" / "seoul.json").write_text('{"offsets": {}, "nod')
    assert any("not valid JSON" in m for m in check_dist.check_dist(d))


def test_the_page_copy_may_not_state_a_count(check_dist, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<p>from 553 cities</p>")
    (web / "llms.txt").write_text("hundreds of cities")
    problems = check_dist.check_copy(web)
    assert len(problems) == 2
    (web / "index.html").write_text("<p>from more than a hundred cities</p>")
    (web / "llms.txt").write_text("the cities listed in index.json")
    assert check_dist.check_copy(web) == []


@pytest.mark.parametrize("missing", ["hoverCellCount", "modeChannels"])
def test_an_index_written_by_an_older_emitter_is_refused(check_dist, tmp_path, missing):
    """A long build writes index.json at the end from the module it imported at
    the start, so the artifacts can be newer than the index beside them. Both
    fields are the page's only defence against a mixed build; `if key in idx`
    let exactly that index through with the guards silently off."""
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    del idx[missing]
    (d / "index.json").write_text(json.dumps(idx))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any(missing in m for m in problems), problems
    assert any("reindex" in m for m in problems), "the refusal must name the remedy"


def test_the_summary_survives_an_index_missing_its_optional_fields(check_dist, tmp_path, capsys):
    """check_dist declared the build consistent and then died with a KeyError
    printing its own summary, because it never required the fields it read.

    It used to assert `bands == 1` from an expression the test computed the
    same way the code does, and never called main() -- so reverting the fix
    kept it green. It runs the real entry point now.

    It also used to prove the point by deleting `attribution`, which is no
    longer an optional field: crediting every source the pipeline consumes is
    a licence obligation and check_dist refuses an index that drops one, so
    such a dist/ is never declared consistent and the summary is never
    reached. The crash-safety question is unchanged, so it is asked of the
    fields that ARE optional -- buildId and solveRes, both read by the
    summary line and neither required anywhere.
    """
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    idx.pop("buildId", None)
    idx.pop("solveRes", None)
    (d / "index.json").write_text(json.dumps(idx))
    import sys
    argv = sys.argv
    sys.argv = ["check_dist", "--dist", str(d), "--web", str(_page_tree(tmp_path, "summary-web")),
                "--no-origins"]
    try:
        check_dist.main()
    except SystemExit as exc:                       # pragma: no cover - only on failure
        raise AssertionError(capsys.readouterr().out) from exc
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "build unstamped" in out, out
    assert "solveRes None" in out, out
    assert "bands 3" in out, out                    # two edges in the fixture
    assert "dist/ is consistent" in out, out
    # ...and the summary still names the credits, which is how an operator
    # sees at a glance that the obligation is met.
    assert "HydroLAKES" in out, out


def test_an_index_without_band_edges_is_refused(check_dist, tmp_path):
    """app.js does `expandRamp(meta.bandEdgesMin)` and fatal()s without it,
    which is a blank page. check_dist called such a dist/ consistent."""
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    del idx["bandEdgesMin"]
    (d / "index.json").write_text(json.dumps(idx))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any("bandEdgesMin" in m for m in problems), problems
    assert any("reindex" in m for m in problems), "the refusal must name the remedy"


def test_band_edges_out_of_order_are_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    idx["bandEdgesMin"] = [60, 30]
    (d / "index.json").write_text(json.dumps(idx))
    assert any("ascending" in m for m in check_dist.check_dist(d, [{"slug": "seoul"}]))


def test_an_empty_offsets_object_is_refused(check_dist, tmp_path):
    """`"offsets" not in payload` passed an empty dict, and the page then
    dropped the route panel silently -- it checks the same two numbers."""
    d = _good_dist(tmp_path)
    (d / "origins" / "seoul.json").write_text(json.dumps({"offsets": {}, "nodes": []}))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any("offsets lacks airports/stations" in m for m in problems), problems


def test_origins_from_two_builds_are_refused(check_dist, tmp_path):
    """Every fixed-width array is n_cells long whatever the solve resolution,
    because the res-4 parent count depends on the land mask -- so all 349
    shipped arrays are the same size and a stale res-5 array passes every
    length check. offsets.airports is the only per-origin fingerprint that
    does move: about 635k at res 5 against 13.7M at res 6.
    """
    d = _good_dist(tmp_path, slugs=("seoul", "tokyo"))
    (d / "origins" / "tokyo.json").write_text(json.dumps(
        {"offsets": {"airports": 635_000, "stations": 640_000}, "nodes": []}))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}, {"slug": "tokyo"}])
    assert any("mixes two builds" in m for m in problems), problems

# --- U24: a build-host path in a PMTiles metadata blob ---------------------
#
# pmtiles.js fetches the first few KB of every archive on load, so the blob is
# served to every visitor; a single unauthenticated Range: 0-4095 GET returns
# it. tippecanoe writes its own argv and input paths in by default. 64ab007
# fixed the emitter and left the artifacts, and water.pmtiles is not produced
# by build-all at all -- so the emitter-side test, which builds a fresh archive
# with today's code and asserts on that, structurally cannot see a shipped
# file. Confirmed at review time on the real dist/: water.pmtiles carried
# '/users/' and every sampled origin archive carried '/var/folders/'.

def test_a_build_host_path_in_the_metadata_is_reported(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    _pmtiles(d / "origins" / "seoul.pmtiles",
             metadata=b'{"name":"seoul","generator_options":"-o /Users/someone/x.pmtiles"}')
    warn: list[str] = []
    problems = check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=warn)
    assert problems == [], "this must not block a deploy; the artifact cannot be fixed by one"
    assert any("/users/" in w for w in warn), warn
    assert any("served to every visitor" in w for w in warn), warn


def test_a_gzipped_metadata_blob_is_decoded_before_it_is_scanned(check_dist, tmp_path):
    """The real archives store it gzipped; scanning the raw bytes finds
    nothing and reports clean."""
    d = _good_dist(tmp_path)
    _pmtiles(d / "water.pmtiles", size=8192, gzipped=True,
             metadata=b'{"description":"built in /var/folders/kz/T/tmp1234"}')
    warn: list[str] = []
    check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=warn)
    assert any("/var/folders/" in w for w in warn), warn


def test_an_index_that_drops_a_credit_is_refused(check_dist, tmp_path):
    """HydroLAKES lakes (CC BY 4.0) are drawn on the live map today and the
    live index.json credits seven sources, neither HydroLAKES nor GeoNames
    among them -- the deployed index predates their addition to ATTRIBUTION.
    Nothing could see it, because nothing compared the two.

    Mutation: delete the attribution block from check_dist.check_dist.
    """
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    idx["attribution"] = [a for a in idx["attribution"] if a["name"] != "HydroLAKES"]
    (d / "index.json").write_text(json.dumps(idx))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=[])
    assert any("HydroLAKES" in p for p in problems), problems
    assert any("licence" in p for p in problems), problems


def test_a_clean_metadata_blob_raises_nothing(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    warn: list[str] = []
    assert check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=warn) == []
    assert warn == [], warn


def test_clean_tippecanoe_generator_options_are_not_a_leak(check_dist, tmp_path):
    """V19's fixture, which V19 never landed.

    `"generator_options"` was dropped from PMTILES_METADATA_LEAKS because
    tippecanoe writes that key into EVERY archive it produces: the detector
    fired 100 % of the time, carried no signal, and would have failed every
    deploy on a clean build. Nothing tested that, though -- the existing
    leak fixture pairs `generator_options` with `/Users/someone/x.pmtiles`, so
    it is caught by the `/users/` prefix whether or not the token is in the
    tuple, and re-adding the token today left all 31 tests in this file green.
    The claim V19 rests on was therefore unguarded and the deadlock SEC5-2
    removed could come back silently.

    This is the missing half: a real tippecanoe options string with no host
    path in it, which must raise nothing.

    Mutation performed and reverted: add "generator_options" back to
    PMTILES_METADATA_LEAKS -> red.
    """
    d = _good_dist(tmp_path)
    _pmtiles(d / "origins" / "seoul.pmtiles",
             metadata=b'{"name":"seoul","format":"pbf","generator":"tippecanoe v2.78.0",'
                       b'"generator_options":"tippecanoe -o out.pmtiles -l bands -z 12 '
                       b'-Z 0 --no-tile-compression --drop-densest-as-needed"}')
    warn: list[str] = []
    assert check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=warn) == []
    assert warn == [], (
        "a clean tippecanoe archive is reported as leaking a build-host path; "
        "the detector fires on every build and therefore says nothing")


def test_the_leak_scan_survives_a_header_it_cannot_read(check_dist, tmp_path):
    """A zero-length or absurd metadata range must not raise out of the gate."""
    d = _good_dist(tmp_path)
    _pmtiles(d / "origins" / "seoul.pmtiles", metadata=b"")
    warn: list[str] = []
    check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=warn)
    assert warn == []


# ---- the exit code, and the refusals nothing asserted -------------------
#
# deploy_verify.sh reads ONE thing from this script: its exit status. Nothing
# asserted it. Deleting `sys.exit(1)` from main() left every test above green
# and turned the artifact gate into a program that prints its complaints and
# then lets the rsync run.

def _page_tree(tmp_path, name="page"):
    """A web/ the copy gate accepts: it now refuses a missing tree outright."""
    web = tmp_path / name
    web.mkdir(exist_ok=True)
    (web / "index.html").write_text("<!doctype html><title>x</title>")
    (web / "llms.txt").write_text("x")
    return web


def _run_main(check_dist, d, tmp_path, capsys, extra=()):
    import sys
    web = _page_tree(tmp_path)
    argv = sys.argv
    sys.argv = ["check_dist", "--dist", str(d), "--web", str(web), "--no-origins", *extra]
    try:
        check_dist.main()
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv = argv
    return code, capsys.readouterr().out


def test_a_consistent_dist_exits_zero(check_dist, tmp_path, capsys):
    code, out = _run_main(check_dist, _good_dist(tmp_path), tmp_path, capsys)
    assert code == 0, out


def test_a_broken_dist_exits_nonzero(check_dist, tmp_path, capsys):
    """Mutation: delete `sys.exit(1)` from check_dist.main()."""
    d = _good_dist(tmp_path)
    (d / "origins" / "seoul.bin").write_bytes(b"\0" * 4)      # wrong length
    code, out = _run_main(check_dist, d, tmp_path, capsys)
    assert code != 0, f"a broken dist/ exited 0, so the deploy would proceed:\n{out}"
    assert "PROBLEMS" in out, out


def test_a_missing_index_exits_nonzero(check_dist, tmp_path, capsys):
    d = _good_dist(tmp_path)
    (d / "index.json").unlink()
    code, out = _run_main(check_dist, d, tmp_path, capsys)
    assert code != 0, out


# ---- refusal messages asserted by nothing ------------------------------
#
# Two of these are exactly the states cli._reindex's own test fixture writes,
# so check_dist would refuse a dist/ that reindex had just called complete.

def test_a_rail_array_of_the_wrong_length_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    # One cell short of N_CELLS, derived rather than typed: written as a bare
    # byte count this test passed a CORRECT length and proved nothing.
    (d / "origins" / "seoul.rail.bin").write_bytes(b"\0" * 2 * (N_CELLS - 1))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=[])
    assert any("rail.bin" in p for p in problems), problems


def test_a_rail_json_without_stations_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    (d / "origins" / "seoul.rail.json").write_text('{"fields":[]}')
    problems = check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=[])
    assert problems, "a rail table with no stations key passed the gate"


def test_an_origin_json_without_offsets_is_refused(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    (d / "origins" / "seoul.json").write_text("{}")
    problems = check_dist.check_dist(d, [{"slug": "seoul"}], warn_out=[])
    assert problems, "an origin json with no offsets passed the gate"


def test_a_missing_web_tree_is_reported_not_silently_empty(check_dist, tmp_path):
    """check_copy returned [] for a --web path that does not exist, so a typo
    in deploy_verify.sh would have skipped the page gate in silence."""
    problems = check_dist.check_copy(tmp_path / "no-such-tree")
    assert problems, "a missing web/ tree reported no problems at all"
