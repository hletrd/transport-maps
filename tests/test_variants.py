"""Exclusion variants ("avoid flights / ferries / trains"): built into their own
tree, slimmer than the full set, never mistaken for it, and offered only when
complete."""

import json

import numpy as np
import pytest

from transport_maps import cli, variants
from transport_maps.graph import build, ground

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


def test_a_variant_is_slim_no_zoom_7_level_and_no_reading_tier(monkeypatch, tmp_path):
    written, calls = _run_variant(monkeypatch, tmp_path, "rail")
    assert calls["max_zoom"] == [variants.VARIANT_MAX_ZOOM] * 2
    assert calls["skip_native"] == [True, True]
    assert not list((tmp_path / "v" / "no-rail" / "origins").glob("*.r6.bin"))


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
    monkeypatch.setattr(ground, "hex_edges", lambda idx: _tagged(0))
    monkeypatch.setattr(build, "_span_edges", lambda idx: _tagged(6))
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


def test_a_variant_writes_no_override(monkeypatch, tmp_path):
    """The override refers to reading-tier slots; a variant ships no reading tier."""
    written, _ = _run_variant(monkeypatch, tmp_path, "air")
    assert not [p for p in written if p.name.endswith(".over.bin")]
