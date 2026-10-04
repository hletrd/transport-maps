import json
from typing import ClassVar

import numpy as np

from transport_maps import config
from transport_maps.emit import index, modes


class FakeIndex:
    cells: ClassVar[list[str]] = ["8530e08ffffffff", "8530e087fffffff", "85754e63fffffff"]
    n_cells = 3


def test_hover_cell_ids_are_sorted_ascending(tmp_path):
    out = tmp_path / "hover_cells.bin"
    index.write_hover_cells(FakeIndex(), out)
    ids = np.frombuffer(out.read_bytes(), dtype="<u8")
    assert len(ids) > 0
    assert (np.diff(ids.astype(object)) > 0).all()


def test_hover_cells_from_the_builds_list_are_the_same_bytes(tmp_path):
    """R3: the build writes hover_cells.bin from the parent list it hands
    every writer instead of recomputing it; the file must not change."""
    from transport_maps.emit import hover

    index.write_hover_cells(FakeIndex(), tmp_path / "derived.bin")
    index.write_hover_cells(FakeIndex(), tmp_path / "passed.bin",
                            parents=hover.hover_cells(FakeIndex()))
    assert (tmp_path / "passed.bin").read_bytes() == (tmp_path / "derived.bin").read_bytes()


# --- Attribution (C2) --------------------------------------------------------
#
# The licence firewall proves only that no commercial flight records leaked
# into dist/. It says nothing about crediting the open sources that legitimately
# did, so without these tests every gate reports green while the CC-BY-SA and
# ODbL redistribution obligations go unmet.

REQUIRED_ATTRIBUTION = {
    "Wikipedia": "CC BY-SA",
    "OpenStreetMap": "ODbL",
    "GRIP4": None,
    "OurAirports": None,
    "Natural Earth": None,
    # borders.pmtiles (emit/borders.py); public domain, credited all the same.
    "LSIB": "Public Domain",
    "GeoNames": "CC BY",
    "HydroLAKES": "CC BY",
    # The fitted cruise speed and climb/descent penalty are derived from their
    # data, so the ODbL attribution obligation applies to us too.
    "adsb.lol": "ODbL",
}


def _written_index(tmp_path) -> dict:
    out = tmp_path / "index.json"
    index.write_index(
        [{"slug": "seoul", "name": "Seoul", "lat": 37.5665, "lon": 126.9780}], out
    )
    return json.loads(out.read_text(encoding="utf-8"))


def test_index_json_attributes_every_required_source(tmp_path):
    payload = _written_index(tmp_path)
    assert payload["attribution"], "index.json ships no attribution at all"

    by_name = {entry["name"]: entry for entry in payload["attribution"]}
    for required, licence_fragment in REQUIRED_ATTRIBUTION.items():
        match = next((v for k, v in by_name.items() if required in k), None)
        assert match is not None, f"index.json does not attribute {required}"
        assert match["licence"].strip(), f"{required} has an empty licence"
        assert match["url"].strip(), f"{required} has no url"
        if licence_fragment is not None:
            assert licence_fragment in match["licence"], (
                f"{required} must ship under {licence_fragment}, got {match['licence']!r}"
            )


def test_attribution_entries_are_complete_records(tmp_path):
    """Every entry must carry all four fields, so a half-filled row cannot pass
    the per-source lookup above by name alone.
    """
    payload = _written_index(tmp_path)
    for entry in payload["attribution"]:
        assert set(entry) == {"name", "licence", "url", "usedFor"}
        assert all(str(v).strip() for v in entry.values())


def test_index_json_advertises_rail_detail(tmp_path):
    """The page asks for {slug}.rail.bin/.rail.json only when this key is
    present; a build that drops it silently loses station naming.
    """
    assert _written_index(tmp_path)["railDetail"] is True


def test_readme_documents_the_same_sources():
    """The obligation is on the artifact AND on the repo that produces it, and
    the two lists must not drift apart.
    """
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    for entry in index.ATTRIBUTION:
        assert entry["name"] in readme, f"README.md does not credit {entry['name']}"
        assert entry["licence"] in readme, f"README.md omits {entry['name']}'s licence"


def test_an_origins_file_with_no_origins_is_refused(tmp_path):
    """A valid index.json listing nothing is a page that throws on cities[0]."""
    import pytest

    empty = tmp_path / "origins.toml"
    empty.write_text("# nothing here\norigin = []\n")
    with pytest.raises(ValueError, match="no origins"):
        index.load_origins(empty)
    (tmp_path / "none.toml").write_text("title = 'x'\n")
    with pytest.raises(ValueError, match="no origins"):
        index.load_origins(tmp_path / "none.toml")


def test_index_json_can_carry_the_build_identity_the_hover_count_and_the_graph_flags(tmp_path):
    from transport_maps.sources import _fetch

    out = tmp_path / "index.json"
    # What the build read (G2): every input it checked, as sources/_fetch
    # recorded it. Mutation: drop "inputs" from build_identity -> red.
    _fetch.record("https://example.invalid/land.zip", {"sha256": "ab" * 32, "size": 3})
    identity = index.build_identity()
    assert set(identity) == {"inputsHash", "buildId", "builtAt", "gitHead", "inputs"}
    assert identity["buildId"].startswith(identity["inputsHash"] + "-")
    index.write_index([{"slug": "seoul", "name": "Seoul", "lat": 37.5, "lon": 127.0}], out,
                      hover_cell_count=90_740, graph={"rail": True, "ferry": False}, identity=identity)
    payload = json.loads(out.read_text())
    assert payload["hoverCellCount"] == 90_740
    assert payload["graph"] == {"rail": True, "ferry": False}
    assert payload["buildId"] == identity["buildId"] and payload["builtAt"] == identity["builtAt"]
    assert payload["modeChannels"] == list(modes.CHANNELS)
    assert payload["inputs"] == {"https://example.invalid/land.zip": {"sha256": "ab" * 32, "size": 3}}


def test_the_input_fingerprints_do_not_move_the_resume_key():
    """`inputsHash` is what `--skip-existing` trusts; the data reach that key
    through the graph digest. A refetched crawl must not by itself void a
    resume. Mutation: hash `_fetch.used()` into inputsHash -> red."""
    from transport_maps.sources import _fetch

    before = index.build_identity()["inputsHash"]
    _fetch.record("wikipedia:airline-destinations", {"fetchedTo": "2026-10-03T00:00:00+00:00"})
    after = index.build_identity()
    assert after["inputsHash"] == before
    assert "wikipedia:airline-destinations" in after["inputs"]


def test_index_json_carries_the_contract_version_the_contract_names(tmp_path):
    """`contractVersion` is in every index.json, as a plain integer, and it is
    the number docs/contract.md says is current -- the expectation comes from
    the document, not from the constant under test.

    Mutations performed (2026-10-02), each RED: drop the payload entry
    (KeyError); set CONTRACT_VERSION = 3 (disagrees with the document); write
    it as the string "2" (not an int).
    """
    import re

    doc = (config.ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
    m = re.search(r"`emit/index\.py:CONTRACT_VERSION`, now \*\*(\d+)\*\*", doc)
    assert m, "docs/contract.md no longer states the current contract version"
    payload = _written_index(tmp_path)
    version = payload["contractVersion"]
    assert type(version) is int, f"contractVersion is {type(version).__name__}, not int"
    assert version == int(m.group(1))
    # Version 1 is what an index.json WITHOUT the field means; a writer that
    # emits 1 (or less) claims the pre-version layout for a file that has it.
    assert version >= 2


def test_the_build_identity_moves_with_the_inputs(monkeypatch):
    before = index.build_identity()["inputsHash"]
    monkeypatch.setattr(index.config, "HOVER_RES", 3)
    assert index.build_identity()["inputsHash"] != before


def test_mode_detail_reads_the_calibration_it_describes(monkeypatch):
    """The tooltips hard-coded 200/75/35/30, equal to calibration.toml only by
    luck; a 'city over 200,000.0' also reached every road tooltip."""
    from transport_maps.graph import rail

    detail = index.mode_detail()
    assert "200,000 people" in detail["highway"] and "200,000.0" not in detail["highway"]
    assert "GRIP4 class" not in detail["highway"]
    rc = rail.load_rail_calibration()
    assert f"{rc.tiers['high_speed'].speed_kmh:.0f} km/h" in detail["rail"]
    assert f"{rc.tiers['commuter'].speed_kmh:.0f} km/h" in detail["rail"]
    # The charge the page quotes is boarding AND alighting. It used to quote
    # boarding alone and so said 15 minutes where the journey pays 20.
    assert f"{rc.boarding_min + rc.alighting_min:.0f} min" in detail["rail"]
    # The model uses the straight-line chord between stops times a detour
    # factor; `sources/osm.py` states geometry is never consulted, so the
    # tooltip must not claim the train follows the track.
    assert "along the track" not in detail["rail"]

    def fake(path=None):
        tiers = {**rc.tiers,
                 "high_speed": rail.RailTier(speed_kmh=321.0, stop_overhead_min=5.0)}
        return rail.RailCalibration(detour_factor=1.2, boarding_min=15.0,
                                    alighting_min=5.0, tiers=tiers)

    monkeypatch.setattr(rail, "load_rail_calibration", fake)
    assert "321 km/h" in index.mode_detail()["rail"]


def test_the_road_prose_says_halved_only_when_the_factor_is_two(monkeypatch):
    """CR3-7. "halved inside cities" was a literal rendering of the fitted
    calibration.toml [urban] congestion_factor, true only while it is 2.0.
    The word is now derived from the number.

    Mutations performed (2026-10-02), each RED, each restored:
      - the literal "halved inside cities" back in mode_detail()        -> RED
      - urban_slowdown() returning "halved" whatever the factor         -> RED
      - mode_detail() reading a frozen 2.0 instead of the urban module  -> RED
    """
    from transport_maps.sources import urban

    roads = ("highway", "major road", "minor road")
    assert urban.URBAN_CONGESTION_FACTOR == 2.0, "re-derive: the shipped factor moved"
    prose = index.mode_detail()
    for key in roads:
        assert "halved inside cities" in prose[key], (key, prose[key])

    monkeypatch.setattr(urban, "URBAN_CONGESTION_FACTOR", 2.5)
    prose = index.mode_detail()
    for key in roads:
        assert "halved" not in prose[key], (key, prose[key])
        assert "divided by 2.5 inside cities" in prose[key], (key, prose[key])
    # The roadless track is not in the urban regime and says nothing about it.
    assert "inside cities" not in prose["track"]
    assert index.urban_slowdown(1.75) == "divided by 1.75"
    assert index.urban_slowdown(2.0) == "halved"


def test_origin_slugs_are_validated_where_they_are_read(tmp_path):
    import pytest

    for bad in ("../x", "-seoul", "seo ul", ".hidden", "a/b"):
        f = tmp_path / "o.toml"
        f.write_text(f'[[origin]]\nslug = "{bad}"\nname = "X"\nlat = 0.0\nlon = 0.0\n')
        with pytest.raises(ValueError, match="invalid origin slug"):
            index.load_origins(f)


def test_the_page_credit_fallbacks_agree_with_the_emitters_licences():
    """web/app.js repeats GeoNames and HydroLAKES in PAGE_CREDITS so a build
    whose index.json predates their rows still credits them; the licence
    strings must be the emitter's, not a second opinion."""
    import re

    app = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
    block = app[app.index("const PAGE_CREDITS = ["):]
    block = block[: block.index("];")]
    page = dict(re.findall(r'name: "([^"]+)", licence: "([^"]+)"', block))
    ours = {a["name"]: a["licence"] for a in index.ATTRIBUTION}
    repeated = {n: lic for n, lic in page.items() if n in ours}
    assert repeated, "PAGE_CREDITS no longer repeats an emitter source; drop this test"
    for name, lic in repeated.items():
        assert lic == ours[name], f"{name}: page says {lic}, emitter says {ours[name]}"


def test_build_identity_is_sampled_when_it_is_called_not_when_the_build_ends(monkeypatch):
    """The build stamps itself with the inputs it USED, not with the tree as it
    stands when it finishes. build_identity() reads the git head and hashes
    calibration.toml and origins.toml at call time, so calling it as the last
    statement of a sixteen-hour build recorded a checkout 38 commits ahead of
    the one that weighted the graph.

    This test used to edit the REAL calibration.toml in the working tree and
    restore it in a finally. Two problems, both real: _git_head() runs
    `git status --porcelain`, so any build or reindex that called
    build_identity() inside that window stamped itself `<head>-dirty` with a
    wrong inputsHash -- the exact defect a71954d was written to fix -- and a
    hard kill during the window left the tracked file modified. It reads a
    stubbed hash instead, which tests the same property without touching the
    repository.
    """
    from transport_maps.emit import index as index_mod

    monkeypatch.setattr(index_mod, "_git_head", lambda: "frozen-head")
    contents = {"cal": b"speed = 90\n", "origins": b"[[origin]]\n"}

    def fake_sha256(path):
        import hashlib
        key = "cal" if path.name == "calibration.toml" else "origins"
        return hashlib.sha256(contents[key]).hexdigest()

    monkeypatch.setattr(index_mod, "_sha256", fake_sha256)

    at_start = index_mod.build_identity()
    contents["cal"] = b"speed = 95\n"          # the mid-build edit
    at_end = index_mod.build_identity()

    assert at_start["inputsHash"] != at_end["inputsHash"], (
        "build_identity must reflect the file it read; if this is equal the test "
        "cannot detect an end-of-build sample")
    # Both hand-edited inputs are covered, not only the first.
    contents["cal"] = b"speed = 90\n"
    contents["origins"] = b"[[origin]]\n[[origin]]\n"
    assert index_mod.build_identity()["inputsHash"] != at_start["inputsHash"], (
        "origins.toml is not in the identity")


def test_build_identity_does_not_touch_the_working_tree(monkeypatch, tmp_path):
    """A guard on the guard: nothing in this module may write to a tracked
    file, because a dirty tree changes what _git_head() reports for any build
    running at the same time."""
    from transport_maps import config

    cal = config.ROOT / "calibration.toml"
    before = cal.read_bytes()
    from transport_maps.emit import index as index_mod
    monkeypatch.setattr(index_mod, "_git_head", lambda: "frozen-head")
    index_mod.build_identity()
    assert cal.read_bytes() == before


def test_write_index_uses_the_mode_prose_it_is_given(tmp_path):
    """mode_detail() re-reads calibration.toml; called at write time that is
    hours after the graph was weighted with those constants."""
    from transport_maps.emit import index as index_mod

    out = tmp_path / "index.json"
    index_mod.write_index([{"slug": "a", "name": "A", "lat": 0, "lon": 0}], out,
                          modes_detail={"rail": "frozen at build start"})
    assert json.loads(out.read_text())["modeDetail"] == {"rail": "frozen at build start"}


def test_every_fitted_range_in_the_mode_prose_reads_low_to_high():
    """T23 fixed one backwards range and nothing stops the next one.

    The speed table is ordered by road class, not by speed, so classes 2 and 3
    (57 and 50 km/h) printed "fitted at 57-50 km/h" -- shipped in index.json
    and read out in the page's route tooltip beside an ascending "18-25".
    Reverting the min()/max() left all thirteen tests in this file green.
    """
    import re

    prose = index.mode_detail()
    ranges = [(m.group(1), m.group(2), key)
              for key, text in prose.items()
              for m in re.finditer(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\s*km/h", text)]
    assert ranges, f"no speed range found in the mode prose: {prose}"
    for lo, hi, key in ranges:
        assert float(lo) <= float(hi), f"{key}: {lo}-{hi} km/h reads backwards"


def test_the_mode_prose_covers_every_channel_the_page_expects():
    """Six surface mode names live in four places and only MODE_NAMES was
    pinned to modes.CHANNELS. Add a seventh channel and the suite goes green
    while mode_detail() silently lacks it, so the new mode's route tooltip is
    empty. (ARCH4-3.)"""
    from transport_maps.emit import modes

    prose = index.mode_detail()
    missing = [c for c in modes.CHANNELS if c not in prose]
    assert not missing, f"mode_detail() has no prose for {missing}"
    for c in modes.CHANNELS:
        assert prose[c].strip(), f"{c}: empty prose"


def test_duplicate_origin_names_are_warned_about_not_rejected(tmp_path, caplog):
    """Four names in the 553-origin set belong to two cities each -- Hyderabad,
    Suzhou, Fuzhou, Taizhou. The data is legitimate; the picker sorting by name
    is what makes it a problem, so this warns and the page disambiguates.
    """
    import logging

    p = tmp_path / "origins.toml"
    p.write_text(
        '[[origin]]\nslug = "hyderabad"\nname = "Hyderabad"\nlat = 17.4\nlon = 78.5\n'
        '[[origin]]\nslug = "hyderabad-pk"\nname = "Hyderabad"\nlat = 25.4\nlon = 68.4\n'
        '[[origin]]\nslug = "seoul"\nname = "Seoul"\nlat = 37.6\nlon = 127.0\n')
    with caplog.at_level(logging.WARNING):
        out = index.load_origins(p)
    assert [o["slug"] for o in out] == ["hyderabad", "hyderabad-pk", "seoul"]
    assert "Hyderabad" in caplog.text and "more than once" in caplog.text


def test_unique_origin_names_warn_about_nothing(tmp_path, caplog):
    import logging

    p = tmp_path / "origins.toml"
    p.write_text('[[origin]]\nslug = "seoul"\nname = "Seoul"\nlat = 37.6\nlon = 127.0\n')
    with caplog.at_level(logging.WARNING):
        index.load_origins(p)
    assert "more than once" not in caplog.text


def test_the_index_carries_country_only_when_origins_toml_does(tmp_path):
    """The page needs it to tell two cities of one name apart, and falls back
    to places.json when the build predates the field."""
    out = tmp_path / "index.json"
    index.write_index(
        [{"slug": "a", "name": "Hyderabad", "lat": 0.0, "lon": 0.0, "country": "IN"},
         {"slug": "b", "name": "Seoul", "lat": 1.0, "lon": 1.0}], out)
    listed = json.loads(out.read_text())["origins"]
    assert listed[0]["country"] == "IN"
    assert "country" not in listed[1]
