"""The deploy gate must refuse every kind of inconsistent dist/ it exists for."""

import importlib.util
import json
import struct

import pytest

from transport_maps import config
from transport_maps.emit import water
from transport_maps.emit.index import ATTRIBUTION
from transport_maps.emit.modes import CHANNELS


@pytest.fixture(scope="module")
def check_dist():
    spec = importlib.util.spec_from_file_location("check_dist", config.ROOT / "scripts" / "check_dist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N_CELLS = 3


def _pmtiles(path, size=4096, metadata=b'{"name":"water"}', gzipped=False,
             tile_type=0, zooms=(0, 0)):
    if gzipped:
        import gzip
        metadata = gzip.compress(metadata)
    head = bytearray(127)
    head[:7] = b"PMTiles"
    head[7] = 3
    head[99], head[100], head[101] = tile_type, *zooms
    # root dir at 127 (len 100), metadata at 227, leaves after it (len 0), then tiles
    mlen = len(metadata)
    struct.pack_into("<QQQQQQQQ", head, 8, 127, 100, 227, mlen,
                     227 + mlen, 0, 227 + mlen, size - 227 - mlen)
    body = bytearray(b"\0" * (size - 127))
    body[227 - 127:227 - 127 + mlen] = metadata
    path.write_bytes(bytes(head) + bytes(body))


def _water(path, layers=(water.LAYER,), zooms=(water.MIN_ZOOM, water.MAX_ZOOM), tile_type=1,
           metadata=None, **kw):
    """A water archive shaped like the one tippecanoe writes: MVT, the
    emitter's zoom range, and a vector_layers entry per layer."""
    if metadata is None:
        metadata = json.dumps({"name": "water", "format": "pbf", "vector_layers": [
            {"id": i, "minzoom": zooms[0], "maxzoom": zooms[1]} for i in layers]}).encode()
    _pmtiles(path, metadata=metadata, tile_type=tile_type, zooms=zooms, **kw)


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
    _water(d / "water.pmtiles")
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


def test_the_modes_width_comes_from_the_index_the_page_reads(check_dist, tmp_path):
    """A seventh channel must not drift past the gate, and the gate must judge
    the arrays by the channel list the PAGE reads them by -- index.json's
    `modeChannels` -- not by the emitter this checkout imports (J1b(d), AA44).

    Mutation: `n_channels = len(CHANNELS)` in place of the index's count -> RED
    (the seven-channel dist/ below is refused although it is consistent).
    """
    d = _good_dist(tmp_path)
    p = d / "origins" / "seoul.modes.bin"
    p.write_bytes(b"\0" * 2 * (len(CHANNELS) + 1) * N_CELLS)
    assert any("seoul.modes.bin" in m for m in check_dist.check_dist(d))
    idx = json.loads((d / "index.json").read_text())
    idx["modeChannels"].append("hovercraft")
    (d / "index.json").write_text(json.dumps(idx))
    assert check_dist.check_dist(d) == []
    # The override entry width follows the same count: 4 + 2 + 2 * channels.
    idx["overrideUrlSuffix"] = ".over.bin"
    (d / "index.json").write_text(json.dumps(idx))
    (d / "origins" / "seoul.over.bin").write_bytes(b"\0" * (4 + 2 + 2 * (len(CHANNELS) + 1)))
    assert check_dist.check_dist(d) == []
    # An explicit expectation is still checked against the index.
    assert any("modeChannels has 7 entries, expected 6" in m
               for m in check_dist.check_dist(d, n_channels=len(CHANNELS)))


def test_the_emitter_channel_count_is_only_a_fallback(check_dist, tmp_path):
    """No `modeChannels` is itself refused (the page then cannot check the
    channel order), and the arrays are measured against the emitter's count,
    so the one message names the real cause instead of every origin.

    Mutation: return 0 from the fallback branch of `_channel_count` -> RED.
    """
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    del idx["modeChannels"]
    (d / "index.json").write_text(json.dumps(idx))
    problems = check_dist.check_dist(d)
    assert problems == [
        "index.json has no modeChannels: the page cannot check the .modes.bin channel "
        "order. Run `uv run transport-maps reindex`."], problems
    idx["modeChannels"] = "rail,ferry"
    (d / "index.json").write_text(json.dumps(idx))
    problems = check_dist.check_dist(d)
    assert len(problems) == 1 and "not a list of channel names" in problems[0], problems


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


#: Every shape of count that has actually shipped or could. The four-digit
#: rows are the ones that matter now: the pattern was `[0-9]{3}` -- exactly
#: three digits -- so it caught "553 cities" and missed every form of 1,464.
#: The gate stopped gating at precisely the transition it exists to police.
#: The spelled-out rows were live on the site in five places while the numeric
#: pattern could never have seen them.
COUNTS_THAT_MUST_BE_CAUGHT = [
    "from 553 cities",
    "from 1464 cities",
    "from 1,464 cities",
    "1464 origins",
    "1464 departure cities",
    "over 1464 cities",
    "hundreds of cities",
    "more than five hundred cities",
    "from a thousand departure cities",
    "from two thousand origins",
]

#: Copy that names no count. "the cities in data/origins.toml" is the README's
#: phrasing and "cities on every inhabited continent" is the meta
#: description's, so both are load-bearing: a regex that fires on either one
#: makes the gate unpassable and gets deleted.
COUNTS_THAT_MUST_PASS = [
    "the cities listed in index.json",
    "from cities on every inhabited continent",
    "the cities in data/origins.toml",
    "Global travel-time isochrones from cities worldwide",
    "reach any point on Earth from the departure cities",
]


@pytest.mark.parametrize("claim", COUNTS_THAT_MUST_BE_CAUGHT)
def test_the_page_copy_may_not_state_a_count(check_dist, tmp_path, claim):
    """Mutation performed and reverted: restore `[0-9]{3}` -> the six
    four-digit rows go red; drop the spelled-out alternation -> three more.
    """
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(f"<p>{claim}</p>")
    (web / "llms.txt").write_text("nothing to see")
    problems = check_dist.check_copy(web)
    assert len(problems) == 1, (
        f"{claim!r} passed the page-copy gate; the count must come from "
        "index.json at runtime")
    assert "index.json" in problems[0], "the refusal does not name the remedy"


@pytest.mark.parametrize("clean", COUNTS_THAT_MUST_PASS)
def test_copy_that_names_no_count_is_left_alone(check_dist, tmp_path, clean):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(f"<p>{clean}</p>")
    (web / "llms.txt").write_text("the cities listed in index.json")
    assert check_dist.check_copy(web) == [], (
        f"{clean!r} was refused, and it states no count")


def test_the_real_page_copy_passes_its_own_gate(check_dist):
    """The five live violations this widening exposed are fixed in the same
    commit. If a sixth appears, it fails here rather than on the deploy."""
    from transport_maps import config
    assert check_dist.check_copy(config.ROOT / "web") == []


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
    length check. offsets.airports is a per-origin fingerprint that does move:
    about 635k at res 5 against 13.7M at res 6.
    """
    d = _good_dist(tmp_path, slugs=("seoul", "tokyo"))
    (d / "origins" / "tokyo.json").write_text(json.dumps(
        {"offsets": {"airports": 635_000, "stations": 640_000}, "nodes": []}))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}, {"slug": "tokyo"}])
    assert any("mixes two builds" in m for m in problems), problems


def _universe(d, airports):
    (d / "origins" / "seoul.json").write_text(json.dumps(
        {"offsets": {"airports": airports, "stations": airports + 200}, "nodes": []}))


def test_the_node_universe_must_fit_the_hover_cells(check_dist, tmp_path):
    """C13-11 / V13-4. U22 named the bound 49·H <= n_cells <= 343·H and it
    never landed. Re-derived: hover_cells.bin is the set of hoverRes parents
    of the solver cells, and every solver cell is at solveRes or fineRes, so
    each hover cell holds between 1 and 7^(fineRes - hoverRes) of them:
    H <= offsets.airports <= 343·H. The 49·H lower bound was false: a
    coastal hover cell can hold a single land cell.

    Mutations performed (2026-10-02), each RED, each restored:
      - delete the bound                          -> RED (both refusals pass)
      - lower bound 49 * n_cells (U22's original)  -> RED (H itself refused)
      - upper bound 7 ** (fine - hover - 1)       -> RED (343·H refused)
    """
    import h3

    d = _good_dist(tmp_path)
    most = 7 ** (config.FINE_RES - config.HOVER_RES)
    # The ceiling is attained: a hexagonal hover cell has exactly that many
    # fineRes descendants.
    hexagon = h3.latlng_to_cell(37.5, 127.0, config.HOVER_RES)
    assert not h3.is_pentagon(hexagon)
    assert len(h3.cell_to_children(hexagon, config.FINE_RES)) == most == 343

    for good in (N_CELLS, most * N_CELLS):
        _universe(d, good)
        assert check_dist.check_dist(d) == [], good
    for wrong in (N_CELLS - 1, most * N_CELLS + 1):
        _universe(d, wrong)
        problems = check_dist.check_dist(d)
        assert any("hover_cells.bin come from different builds" in m for m in problems), (
            wrong, problems)


def test_origins_that_disagree_on_the_airport_count_alone_are_refused(
        check_dist, tmp_path):
    """offsets.airports is idx.n_cells, so it moves only with the SOLVE
    resolution. Two builds at the same resolution whose airport sets differ --
    an added snap rule, a re-crawled source, a changed filter -- share it
    exactly, and this gate called them consistent while parsing offsets.stations
    two lines above and throwing it away.

    Measured on the real dist/ at the time this was written: 3,990 airports in
    some origins and 3,996 in others, and the gate passed.

    Mutation performed and reverted: key n_nodes on off["airports"] alone ->
    green, i.e. the mixed build ships.
    """
    d = _good_dist(tmp_path, slugs=("seoul", "tokyo"))
    # Same cell count, six more airports: (stations - airports) / 2 is 100 here
    # and 106 there.
    (d / "origins" / "tokyo.json").write_text(json.dumps(
        {"offsets": {"airports": 1000, "stations": 1212}, "nodes": []}))
    problems = check_dist.check_dist(d, [{"slug": "seoul"}, {"slug": "tokyo"}])
    assert any("mixes two builds" in m for m in problems), (
        "two builds sharing a cell count but not an airport set passed the gate "
        f"that exists to stop exactly that: {problems}")
    said = [m for m in problems if "mixes two builds" in m][0]
    assert "100 airports" in said and "106 airports" in said, (
        f"the message does not name the two airport counts: {said}")

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


# --- C16-7.1: the water gate was real and nothing guarded it ---------------
#
# CLAUDE.md names `dist/water.pmtiles` a standing deploy invariant: it is
# static, `build-all` never regenerates it, and without it the page shows NO
# error -- the shore just goes back to being hex-shaped one cell out to sea.
# It says `deploy_verify.sh` refuses without it and `browser_verify.sh` asks
# the map whether water actually rendered. Both refusals work. Neither was
# tested: cycle 16's verifier lane neutered each in turn and measured
#
#   water.pmtiles missing-refusal removed  -> test_check_dist.py  48 passed
#   the three JSON extras dropped          -> test_check_dist.py  48 passed
#   browser_verify.sh's water block deleted-> test_deploy_script.py 12 passed
#
# A warning for whoever revisits this: deleting the WHOLE `REQUIRED_EXTRAS`
# loop does go red, but only through an unrelated gzip-metadata test. Anyone
# who tries that mutation first will wrongly conclude the guard exists. The
# guard has to be per-file, which is what this is.


@pytest.mark.parametrize("extra", ["places.json", "airports.json",
                                   "borders.json", "water.pmtiles"])
def test_each_required_extra_is_refused_when_missing(check_dist, tmp_path, extra):
    """One case per file, because a guard over the tuple passes when one
    member is dropped from it.

    `water.pmtiles` is the one CLAUDE.md singles out, and it is also the one
    whose absence is invisible on the page, so it is the one most likely to
    be quietly removed from the list by someone whose build cannot produce
    it. Parametrised over all four so the list cannot shrink silently.
    """
    d = _good_dist(tmp_path)
    assert check_dist.check_dist(d, [{"slug": "seoul"}]) == [], (
        "the fixture is not a good dist/; this case would pass for the wrong "
        "reason")
    (d / extra).unlink()
    bad = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any(extra in b for b in bad), (
        f"check_dist accepted a dist/ with {extra} missing; it reported {bad}")


def test_the_required_extras_list_still_names_water(check_dist):
    """The list itself, pinned. Dropping `water.pmtiles` from
    `REQUIRED_EXTRAS` makes every test above vacuous at once -- the
    parametrised case would still pass, because it deletes the file and asks
    whether anything complains, and nothing would.
    """
    assert "water.pmtiles" in check_dist.REQUIRED_EXTRAS, (
        "REQUIRED_EXTRAS no longer names water.pmtiles, which CLAUDE.md makes "
        "a standing deploy invariant: without it the page shows no error and "
        "the shore silently goes back to being hex-shaped")
    for name in ("places.json", "airports.json", "borders.json"):
        assert name in check_dist.REQUIRED_EXTRAS, f"{name} left REQUIRED_EXTRAS"


def _advertise(d, **extra):
    idx = json.loads((d / "index.json").read_text())
    idx.update(extra)
    (d / "index.json").write_text(json.dumps(idx))


def test_an_advertised_override_must_exist_and_be_whole_entries(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    _advertise(d, overrideUrlSuffix=".over.bin")
    assert any("seoul.over.bin missing" in m for m in check_dist.check_dist(d))
    entry = 4 + 2 + 2 * len(CHANNELS)
    (d / "origins" / "seoul.over.bin").write_bytes(b"\0" * (entry * 3 - 1))
    assert any("not whole" in m for m in check_dist.check_dist(d))
    (d / "origins" / "seoul.over.bin").write_bytes(b"\0" * entry * 3)
    assert check_dist.check_dist(d) == []


def test_an_offered_variant_must_hold_every_origins_files(check_dist, tmp_path):
    d = _good_dist(tmp_path)
    _advertise(d, variants=[{"exclude": "air", "path": "v/no-air/", "maxZoom": 6}])
    assert any("variant no-air: seoul.pmtiles missing" in m for m in check_dist.check_dist(d))
    vo = d / "v" / "no-air" / "origins"
    vo.mkdir(parents=True)
    for suffix in (".bin", ".air.bin"):
        (vo / f"seoul{suffix}").write_bytes(b"\0" * 2 * N_CELLS)
    (vo / "seoul.modes.bin").write_bytes(b"\0" * 2 * len(CHANNELS) * (N_CELLS - 1))
    (vo / "seoul.json").write_text("{}")
    _pmtiles(vo / "seoul.pmtiles")
    assert any("seoul.modes.bin has" in m for m in check_dist.check_dist(d))
    (vo / "seoul.modes.bin").write_bytes(b"\0" * 2 * len(CHANNELS) * N_CELLS)
    assert check_dist.check_dist(d) == []


def test_an_offered_variant_must_hold_its_reading_tier_and_override(check_dist, tmp_path):
    """The page reads both from the variant's own directory."""
    # The variant is complete and passing before anything below changes it.
    test_an_offered_variant_must_hold_every_origins_files(check_dist, tmp_path)
    d = tmp_path / "dist"
    entry = 4 + 2 + 2 * len(CHANNELS)
    (d / "origins" / "seoul.over.bin").write_bytes(b"\0" * entry)
    _advertise(d, overrideUrlSuffix=".over.bin")
    vo = d / "v" / "no-air" / "origins"
    assert any("variant no-air: seoul.over.bin missing" in m for m in check_dist.check_dist(d))
    (vo / "seoul.over.bin").write_bytes(b"\0" * (entry + 1))
    assert any("variant no-air: seoul.over.bin" in m and "not whole" in m
               for m in check_dist.check_dist(d))
    (vo / "seoul.over.bin").write_bytes(b"\0" * entry)
    assert check_dist.check_dist(d) == []


def test_an_offered_variant_must_hold_its_reading_tier_at_the_full_width(check_dist, tmp_path):
    # The variant is complete and passing before anything below changes it.
    test_an_offered_variant_must_hold_every_origins_files(check_dist, tmp_path)
    d = tmp_path / "dist"
    width = config.READING_SLOTS * 2
    (d / "reading_parents.bin").write_bytes(b"\0" * 8)
    _advertise(d, readingParentCount=1)
    (d / "origins" / "seoul.r6.bin").write_bytes(b"\0" * width)
    vo = d / "v" / "no-air" / "origins"
    assert any("variant no-air: seoul.r6.bin missing" in m for m in check_dist.check_dist(d))
    (vo / "seoul.r6.bin").write_bytes(b"\0" * (width - 2))
    assert any("variant no-air: seoul.r6.bin is" in m for m in check_dist.check_dist(d))
    (vo / "seoul.r6.bin").write_bytes(b"\0" * width)
    assert check_dist.check_dist(d) == []


# --- L12 / E15: water.pmtiles is checked for what it holds, not only its shape
#
# `_pmtiles_ok` reads the header's magic and offsets and nothing else, so it
# passed the 867 MB z0-12 archive (42.7% of its tile section at a zoom no page
# can request) and would pass one whose layer is not called `water` -- which
# the page's `"source-layer": "water"` then draws nothing from, with no error.

def test_the_real_water_archive_shape_passes(check_dist, tmp_path):
    """The positive control, gzipped as tippecanoe writes it, in the shape the
    real archive has (measured on dist/ 2026-10-02: v3, MVT, z0-11, one
    `water` layer)."""
    d = _good_dist(tmp_path)
    _water(d / "water.pmtiles", size=8192, gzipped=True)
    assert check_dist.check_dist(d, [{"slug": "seoul"}]) == []


@pytest.mark.parametrize(("zooms", "why"), [
    ((0, 12), "the old 867 MB archive: z12 tiles no page zoom can request"),
    ((0, 10), "a coast that stops a zoom short of the page"),
    ((2, 11), "nothing to draw at the opening view"),
])
def test_a_water_archive_at_the_wrong_zoom_range_is_refused(check_dist, tmp_path, zooms, why):
    """Mutation performed and reverted: delete the zoom comparison from
    `_water_problems` -> all three cases red."""
    d = _good_dist(tmp_path)
    _water(d / "water.pmtiles", zooms=zooms)
    bad = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any(f"spans z{zooms[0]}-z{zooms[1]}" in b and "stale archive" in b for b in bad), (why, bad)


def test_a_water_archive_without_the_water_layer_is_refused(check_dist, tmp_path):
    """Mutation performed and reverted: `water.LAYER not in ids` -> `False`
    -> red."""
    d = _good_dist(tmp_path)
    _water(d / "water.pmtiles", layers=("ocean", "lakes"))
    bad = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any("vector layers ['lakes', 'ocean'], not 'water'" in b for b in bad), bad


@pytest.mark.parametrize("metadata", [b'{"name":"water"}', b"not json",
                                      b'{"vector_layers":"water"}'])
def test_a_water_archive_whose_layers_cannot_be_read_is_refused(check_dist, tmp_path, metadata):
    """No vector_layers is not the same as the right ones: a gate that only
    looked for a WRONG layer would wave through metadata it could not read.

    Mutation performed and reverted: make the `not isinstance(layers, list)`
    branch append nothing -> red."""
    d = _good_dist(tmp_path)
    _water(d / "water.pmtiles", metadata=metadata)
    bad = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any("metadata has no vector_layers" in b for b in bad), bad


def test_a_raster_water_archive_is_refused(check_dist, tmp_path):
    """Mutation performed and reverted: delete the tile-type comparison -> red."""
    d = _good_dist(tmp_path)
    _water(d / "water.pmtiles", tile_type=2)        # PNG
    bad = check_dist.check_dist(d, [{"slug": "seoul"}])
    assert any("holds tile type 2, not vector" in b for b in bad), bad


def test_the_water_rules_are_applied_to_water_pmtiles_only(check_dist, tmp_path):
    """An origin archive's layer is `bands` and the fixture's origin archive
    has no vector_layers at all; holding it to the water rules would refuse
    every build.

    Mutation performed and reverted: drop the `extra == "water.pmtiles"`
    condition and call `_water_problems` on the origin archives too -> red."""
    d = _good_dist(tmp_path)
    assert check_dist.check_dist(d, [{"slug": "seoul"}]) == []


def test_the_page_draws_the_layer_the_emitter_writes():
    """The other half of the layer check: the gate compares the archive with
    emit/water.py, so the page must read that same name, or the archive and
    the emitter could agree with each other and the page still draw nothing.

    Mutation performed and reverted: `"source-layer": "water"` -> `"coast"` in
    web/app.js -> red."""
    import re

    app = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
    layer = re.search(r'source: WATER_SOURCE, "source-layer": "([^"]+)"', app)
    assert layer, "web/app.js no longer adds a layer from the water source"
    assert layer.group(1) == water.LAYER, (
        f"the page draws source-layer {layer.group(1)!r} and the emitter writes {water.LAYER!r}")
    assert 'url: "pmtiles://./water.pmtiles"' in app, (
        "the page no longer loads water.pmtiles, which REQUIRED_EXTRAS gates")


# --- A6b/A6c: per-origin completion records (transport_maps.progress) --------

def _records(root, slugs=("seoul",), state="complete", inputs="in-1", exclude=None):
    """A record per origin, listing the files on disk at their sizes, as
    `progress.finish` writes it (or as `progress.begin` does, for "writing")."""
    from transport_maps import progress

    for s in slugs:
        rec = {"slug": s, "state": state, "inputsHash": inputs, "buildId": f"{inputs}-t0",
               "exclude": exclude}
        if state == "complete":
            rec["files"] = {p.name: p.stat().st_size for p in (root / "origins").glob(f"{s}.*")}
        path = progress.record_path(root, s)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec))


def test_an_origin_a_build_stopped_inside_is_refused(check_dist, tmp_path):
    """Every length agrees, the node universe agrees -- and the origin is half
    one build and half another, which only its record can say.

    Mutation performed and reverted: the `state != COMPLETE` branch removed
    from `_record_problems` -> red.
    """
    d = _good_dist(tmp_path, slugs=("seoul", "tokyo"))
    _advertise(d, inputsHash="in-1")
    _records(d, slugs=("seoul", "tokyo"))
    assert check_dist.check_dist(d) == []
    _records(d, slugs=("tokyo",), state="writing")
    problems = check_dist.check_dist(d)
    assert len(problems) == 1 and "origins/tokyo: a build stopped while writing it" in problems[0]
    assert "skip-existing" in problems[0], "the refusal names no way forward"


def test_a_recorded_file_that_changed_since_is_refused(check_dist, tmp_path):
    """Mutation performed and reverted: the `files_problem` branch removed -> red."""
    d = _good_dist(tmp_path)
    _records(d)
    p = d / "origins" / "seoul.pmtiles"
    p.write_bytes(p.read_bytes() + b"\0" * 16)          # still a sane PMTiles header
    assert any("seoul.pmtiles is 4,112 bytes, recorded 4,096" in m
               for m in check_dist.check_dist(d))


def test_what_records_cannot_vouch_for_is_reported_not_refused(check_dist, tmp_path):
    """No records at all, an origin without one, and a whole origin from other
    inputs: none is a mixed origin, so none blocks the deploy -- but each is
    said. Mutation performed and reverted: the inputsHash comparison turned
    into a refusal -> red."""
    d = _good_dist(tmp_path, slugs=("seoul", "tokyo"))
    _advertise(d, inputsHash="in-2")
    warn: list = []
    assert check_dist.check_dist(d, warn_out=warn) == [] and warn == []
    _records(d, slugs=("seoul",), inputs="in-1")
    assert check_dist.check_dist(d, warn_out=warn) == []
    assert any(w.startswith("origins/seoul ") and "other inputs" in w for w in warn)
    assert any(w.startswith("origins/tokyo ") and "no completion record" in w for w in warn)


def test_an_offered_variants_records_answer_to_its_own_marker(check_dist, tmp_path):
    """A variant is built by its own run: its records are held against the
    identity in its marker, and one stopped mid-origin is refused there too.

    Mutations performed and reverted, each red: the `_record_problems` call
    for variant roots removed; the variant held against index.json's
    inputsHash instead of its marker's.
    """
    from transport_maps import variants

    test_an_offered_variant_must_hold_every_origins_files(check_dist, tmp_path)
    d = tmp_path / "dist"
    _advertise(d, inputsHash="in-full")
    root = d / "v" / "no-air"
    variants.write_marker(root, "air", ["seoul"], {"inputsHash": "in-air"})
    _records(root, inputs="in-air", exclude="air")
    warn: list = []
    assert check_dist.check_dist(d, warn_out=warn) == [] and warn == []
    _records(root, state="writing", exclude="air")
    problems = check_dist.check_dist(d)
    assert any("v/no-air/origins/seoul: a build stopped while writing it" in m
               and "exclude air" in m for m in problems), problems
