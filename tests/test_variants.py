"""Exclusion variants ("avoid flights / ferries / trains"): built into their own
tree, with coarser tiles than the full set but its reading tier, never mistaken
for it, and offered only when complete."""

import json

import numpy as np
import pytest

from transport_maps import cli, variants
from transport_maps.graph import build, ground
from transport_maps.sources import countries

from .test_cli import _stub_pipeline


def _run_variant(monkeypatch, tmp_path, exclude, coverages=(1.0, 1.0)):
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    calls = {"index": 0, "hover_cells": 0, "max_zoom": [], "skip_native": []}
    _stub_pipeline(monkeypatch, written, coverages=list(coverages))
    monkeypatch.setattr(cli.index, "write_index",
                        lambda *a, **k: calls.__setitem__("index", calls["index"] + 1))
    monkeypatch.setattr(cli.index, "write_hover_cells",
                        lambda idx, out: calls.__setitem__("hover_cells", calls["hover_cells"] + 1))

    def pmtiles(fc, out, **kw):
        calls["max_zoom"].append(kw.get("max_zoom"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")
        written.append(out)

    monkeypatch.setattr(cli.tiles, "write_pmtiles", pmtiles)
    monkeypatch.setattr(cli.bands, "band_feature_collection",
                        lambda *a, **kw: calls["skip_native"].append(kw.get("skip_native"))
                        or {"features": []})
    cli._build_all(exclude=exclude)
    return written, calls


def test_a_variant_writes_its_own_tree_and_never_the_full_sets_files(monkeypatch, tmp_path):
    written, calls = _run_variant(monkeypatch, tmp_path, "ferry")
    root = tmp_path / "v" / "no-ferry"
    assert written and all(root in p.parents for p in written), \
        "every file of a variant goes under dist/v/no-<mode>/"
    assert calls["index"] == 0, "a variant must never rewrite the full set's index.json"
    assert calls["hover_cells"] == 0, "nor the hover_cells.bin the live site reads"
    marker = json.loads((root / variants.MARKER).read_text())
    assert marker["exclude"] == "ferry" and marker["origins"] == ["first", "second"]


def test_a_variant_has_no_zoom_7_level_but_keeps_the_reading_tier(monkeypatch, tmp_path):
    """Without the reading tier a variant printed the ~20 km area's time, which
    at Tinian with ferries avoided was faster than the full map's."""
    written, calls = _run_variant(monkeypatch, tmp_path, "rail")
    assert calls["max_zoom"] == [variants.VARIANT_MAX_ZOOM] * 2
    assert calls["skip_native"] == [True, True]
    got = sorted(p.name for p in (tmp_path / "v" / "no-rail" / "origins").glob("*.r6.bin"))
    assert got == ["first.r6.bin", "second.r6.bin"]


def test_the_full_build_is_not_slim(monkeypatch, tmp_path):
    """The control for the two tests above."""
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    written: list = []
    zooms: list = []
    _stub_pipeline(monkeypatch, written, coverages=[1.0, 1.0])
    monkeypatch.setattr(cli.index, "write_index", lambda *a, **k: None)
    def pmtiles(fc, out, **kw):
        zooms.append(kw.get("max_zoom"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")

    monkeypatch.setattr(cli.tiles, "write_pmtiles", pmtiles)
    cli._build_all()
    assert zooms == [cli.tiles.MAX_ZOOM] * 2
    assert list((tmp_path / "origins").glob("*.r6.bin"))
    assert not (tmp_path / "v").exists()


def test_a_variant_has_no_coverage_floor_but_must_reach_something(monkeypatch, tmp_path):
    """Without flights Honolulu reaches Hawaii and nothing else, correctly."""
    _run_variant(monkeypatch, tmp_path, "air", coverages=(0.004, 0.3))
    with pytest.raises(SystemExit, match="no-air"):
        _run_variant(monkeypatch, tmp_path / "b", "air", coverages=(0.3, 0.0))


def test_the_full_build_keeps_its_coverage_floor(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], coverages=[0.3, 0.3])
    with pytest.raises(SystemExit, match="coverage"):
        cli._build_all()


def test_only_a_variant_complete_for_every_origin_is_offered(tmp_path):
    slugs = ["a", "b"]
    root = variants.variant_dir(tmp_path, "air")
    (root / "origins").mkdir(parents=True)
    for s in slugs:
        for ext in variants.REQUIRED:
            (root / "origins" / f"{s}.{ext}").write_bytes(b"x")
    assert variants.complete_variants(tmp_path, slugs) == [], "no marker: not finished"
    variants.write_marker(root, "air", slugs, {})
    assert variants.complete_variants(tmp_path, slugs) == ["air"]
    assert variants.complete_variants(tmp_path, slugs + ["c"]) == [], "built for fewer origins"
    (root / "origins" / "b.modes.bin").unlink()
    assert variants.complete_variants(tmp_path, slugs) == [], "a missing file"


def test_variant_dir_refuses_an_unknown_mode(tmp_path):
    assert variants.variant_dir(tmp_path, None) == tmp_path
    with pytest.raises(ValueError):
        variants.variant_dir(tmp_path, "bus")


def _tagged(tag):
    return (np.array([tag]), np.array([tag]), np.array([1.0]))


@pytest.mark.parametrize("exclude,absent", [(None, set()), ("air", {1, 2, 3}),
                                            ("ferry", {5}), ("rail", {4})])
def test_build_graph_leaves_out_exactly_the_excluded_modes_edges(monkeypatch, exclude, absent):
    """Each part tagged by a self-loop on its own node, so the matrix says
    which parts were assembled."""
    monkeypatch.setattr(ground, "hex_edges", lambda idx, **kw: _tagged(0))
    monkeypatch.setattr(build, "_span_edges", lambda idx, *a: _tagged(6))
    # Computed once in build_graph and handed to every builder (R5); the
    # builders are stubbed, so the rules are never read.
    monkeypatch.setattr(build, "_border_rules", lambda *a: (None, None, 0.0, None))
    monkeypatch.setattr(build, "_air_edges", lambda *a, **k: _tagged(1))
    monkeypatch.setattr(build, "_access_edges", lambda idx: _tagged(2))
    monkeypatch.setattr(build, "_transfer_edges", lambda idx: _tagged(3))
    monkeypatch.setattr(build, "_rail_edges", lambda *a, **k: _tagged(4))
    monkeypatch.setattr(build, "_ferry_edges", lambda *a, **k: _tagged(5))
    monkeypatch.setattr(build.rail, "load_rail_calibration", lambda: None)
    monkeypatch.setattr(build.ferry, "load_ferry_calibration", lambda: None)

    class Idx:
        n = 7
        has_rail = True

    csr = build.build_graph(Idx(), rail_routes=object(), ferry_links=[1], exclude=exclude)
    present = {i for i in range(7) if csr[i, i]}
    assert present == set(range(7)) - absent


def test_build_graph_derives_the_border_rules_once_and_shares_them(monkeypatch):
    """R5: country and zone are a ~10 M-cell pass each, and build_graph used to
    let hex_edges, spans, rail and ferry each derive their own. Now the
    caller's arrays (cli._build_all_locked has them) go in once, and every
    surface builder receives that same object -- so a builder that quietly
    recomputed, or was handed a copy, shows up as a second call or a
    different identity.

    Mutations performed and reverted, each red: `_span_edges(idx)` without
    the rules; `_rail_edges` without them; `_ferry_edges` without them; the
    country passed to hex_edges taken from a fresh lookup; build_graph
    ignoring the caller's `country`.
    """
    seen: dict = {}
    calls: list = []
    real_rules = build._border_rules

    def counting_rules(idx, country=None, zone=None):
        calls.append(country)
        return real_rules(idx, country, zone)

    monkeypatch.setattr(build, "_border_rules", counting_rules)
    monkeypatch.setattr(countries, "cell_country",
                        lambda cells: pytest.fail("country looked up again"))
    monkeypatch.setattr(ground, "_land_border_min", lambda: 45.0)
    monkeypatch.setattr(ground, "hex_edges",
                        lambda idx, **kw: (seen.__setitem__("hex", kw), _tagged(0))[1])
    monkeypatch.setattr(build, "_span_edges",
                        lambda idx, rules=None: (seen.__setitem__("span", rules), _tagged(6))[1])
    monkeypatch.setattr(build, "_rail_edges",
                        lambda idx, r, cal, rules=None: (seen.__setitem__("rail", rules), _tagged(4))[1])
    monkeypatch.setattr(build, "_ferry_edges",
                        lambda idx, links, cal, dropped_out=None, rules=None:
                        (seen.__setitem__("ferry", rules), _tagged(5))[1])
    for name, tag in (("_air_edges", 1), ("_access_edges", 2), ("_transfer_edges", 3)):
        monkeypatch.setattr(build, name, lambda *a, _t=tag, **k: _tagged(_t))
    monkeypatch.setattr(build.rail, "load_rail_calibration", lambda: None)
    monkeypatch.setattr(build.ferry, "load_ferry_calibration", lambda: None)

    class Idx:
        n = 7
        has_rail = True
        cells = ("a", "b")

    country, zone, speeds = np.array(["KOR", "JPN"]), np.array(["K", "J"]), np.array([5.0, 9.0])
    build.build_graph(Idx(), rail_routes=object(), ferry_links=[1],
                      speeds=speeds, country=country, zone=zone)
    assert calls == [country], f"border rules derived {len(calls)} times"
    rules = seen["span"]
    assert rules[0] is country and rules[1] is zone
    assert seen["rail"] is rules and seen["ferry"] is rules
    assert seen["hex"]["country"] is country and seen["hex"]["zone"] is zone
    assert seen["hex"]["speeds"] is speeds


def test_build_graph_refuses_an_unknown_exclusion():
    with pytest.raises(ValueError):
        build.build_graph(object(), exclude="bus")


def test_files_from_a_later_partial_run_do_not_complete_a_variant(tmp_path):
    """The marker, not the files, says which origins a COMPLETE build covered.

    Origin c's files here came from a later `--exclude air --only c` run, which
    writes files but never the marker. Found by mutation: with c's files absent
    the file check alone masked the marker check, and dropping it stayed green.
    """
    root = variants.variant_dir(tmp_path, "air")
    (root / "origins").mkdir(parents=True)
    for s in ("a", "b", "c"):
        for ext in variants.REQUIRED:
            (root / "origins" / f"{s}.{ext}").write_bytes(b"x")
    variants.write_marker(root, "air", ["a", "b"], {})
    assert variants.complete_variants(tmp_path, ["a", "b", "c"]) == []


def test_index_json_advertises_only_complete_variants(tmp_path):
    from transport_maps.emit import index

    origins = [{"slug": "a", "name": "A", "lat": 0.0, "lon": 0.0}]
    root = variants.variant_dir(tmp_path, "ferry")
    (root / "origins").mkdir(parents=True)
    for ext in variants.REQUIRED:
        (root / "origins" / f"a.{ext}").write_bytes(b"x")
    index.write_index(origins, tmp_path / "index.json", modes_detail={})
    assert json.loads((tmp_path / "index.json").read_text())["variants"] == [], \
        "files without the completion marker are not a finished variant"
    variants.write_marker(root, "ferry", ["a"], {})
    index.write_index(origins, tmp_path / "index.json", modes_detail={})
    got = json.loads((tmp_path / "index.json").read_text())["variants"]
    assert got == [{"exclude": "ferry", "path": "v/no-ferry/", "maxZoom": variants.VARIANT_MAX_ZOOM}]


def test_index_json_advertises_the_override_only_when_every_origin_has_one(tmp_path):
    from transport_maps.emit import index

    origins = [{"slug": s, "name": s, "lat": 0.0, "lon": 0.0} for s in ("a", "b")]
    (tmp_path / "origins").mkdir()
    (tmp_path / "origins" / "a.over.bin").write_bytes(b"")
    index.write_index(origins, tmp_path / "index.json", modes_detail={})
    assert "overrideUrlSuffix" not in json.loads((tmp_path / "index.json").read_text())
    (tmp_path / "origins" / "b.over.bin").write_bytes(b"")
    index.write_index(origins, tmp_path / "index.json", modes_detail={})
    assert json.loads((tmp_path / "index.json").read_text())["overrideUrlSuffix"] == ".over.bin"


def test_a_variant_writes_the_override_with_its_reading_tier(monkeypatch, tmp_path):
    """The route behind the fine reading, so the itinerary matches it."""
    _run_variant(monkeypatch, tmp_path, "air")
    got = sorted(p.name for p in (tmp_path / "v" / "no-air" / "origins").glob("*.over.bin"))
    assert got == ["first.over.bin", "second.over.bin"]


def test_a_set_without_the_reading_tier_is_not_offered(tmp_path):
    """The 2026-09-27 sets: every other file, and a marker, but no .r6.bin."""
    root = variants.variant_dir(tmp_path, "air")
    (root / "origins").mkdir(parents=True)
    for ext in ("pmtiles", "bin", "json", "air.bin", "modes.bin"):
        (root / "origins" / f"a.{ext}").write_bytes(b"x")
    variants.write_marker(root, "air", ["a"], {})
    assert variants.complete_variants(tmp_path, ["a"]) == []


def test_a_full_variant_rebuild_withdraws_the_finished_one_first(monkeypatch, tmp_path):
    """Half rewritten, the tree mixes two builds; it must not stay on offer.

    The rebuild dies on its second origin, so the marker it would write at the
    end never comes: the old one has to have gone at the start.
    """
    root = variants.variant_dir(tmp_path, "air")
    variants.write_marker(root, "air", ["first", "second"], {})
    with pytest.raises(SystemExit):
        _run_variant(monkeypatch, tmp_path, "air", coverages=(0.3, 0.0))
    assert not (root / variants.MARKER).exists()


def test_a_partial_variant_run_leaves_the_finished_one_on_offer(monkeypatch, tmp_path):
    """--only rewrites one origin's files, consistently; it withdraws nothing."""
    root = variants.variant_dir(tmp_path, "air")
    variants.write_marker(root, "air", ["first", "second"], {})
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], coverages=[1.0])
    def pmtiles(fc, out, **kw):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")

    monkeypatch.setattr(cli.tiles, "write_pmtiles", pmtiles)
    monkeypatch.setattr(cli.bands, "band_feature_collection", lambda *a, **kw: {"features": []})
    cli._build_all(only=["first"], exclude="air")
    assert (root / variants.MARKER).exists()
