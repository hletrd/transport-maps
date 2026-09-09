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
        (d / "origins" / f"{s}.json").write_text(json.dumps({"offsets": {}, "nodes": []}))
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
