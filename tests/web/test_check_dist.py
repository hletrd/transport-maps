"""The deploy gate must refuse every kind of inconsistent dist/ it exists for."""

import importlib.util
import json
import struct

import pytest

from transport_maps import config
from transport_maps.emit.modes import CHANNELS


@pytest.fixture(scope="module")
def check_dist():
    spec = importlib.util.spec_from_file_location("check_dist", config.ROOT / "scripts" / "check_dist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N_CELLS = 3


def _pmtiles(path, size=4096):
    head = bytearray(127)
    head[:7] = b"PMTiles"
    head[7] = 3
    # root dir at 127 (len 100), metadata at 227 (len 50), leaves at 277 (len 0), tiles at 277 (len size-277)
    struct.pack_into("<QQQQQQQQ", head, 8, 127, 100, 227, 50, 277, 0, 277, size - 277)
    path.write_bytes(bytes(head) + b"\0" * (size - 127))


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
        "modeChannels": list(CHANNELS), "attribution": [],
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


def test_the_summary_survives_an_index_without_attribution(check_dist, tmp_path, capsys):
    """check_dist declared the build consistent and then died with a KeyError
    printing its own summary, because it never required the field.

    It used to assert `bands == 1` from an expression the test computed the
    same way the code does, and never called main() -- so reverting the fix
    kept it green. It runs the real entry point now.
    """
    d = _good_dist(tmp_path)
    idx = json.loads((d / "index.json").read_text())
    del idx["attribution"]
    (d / "index.json").write_text(json.dumps(idx))
    import sys
    argv = sys.argv
    sys.argv = ["check_dist", "--dist", str(d), "--web", str(tmp_path / "empty-web"),
                "--no-origins"]
    (tmp_path / "empty-web").mkdir()
    try:
        check_dist.main()
    except SystemExit as exc:                       # pragma: no cover - only on failure
        raise AssertionError(capsys.readouterr().out) from exc
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "attribution []" in out, out
    assert "bands 3" in out, out                    # two edges in the fixture
    assert "dist/ is consistent" in out, out


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