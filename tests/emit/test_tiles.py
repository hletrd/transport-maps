import shutil

import pytest

from transport_maps.emit import tiles

SQUARE = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"band": 0, "max_minutes": 120},
        "geometry": {"type": "Polygon", "coordinates": [[
            [126.0, 37.0], [127.0, 37.0], [127.0, 38.0], [126.0, 38.0], [126.0, 37.0]
        ]]},
    }],
}

needs_tippecanoe = pytest.mark.skipif(shutil.which("tippecanoe") is None,
                                      reason="tippecanoe is not on PATH")


@needs_tippecanoe
def test_writes_a_non_empty_pmtiles_file(tmp_path):
    out = tmp_path / "t.pmtiles"
    tiles.write_pmtiles(SQUARE, out)
    assert out.stat().st_size > 0
    assert out.read_bytes()[:7] == b"PMTiles"


@needs_tippecanoe
def test_the_archive_carries_the_layer_the_page_reads(tmp_path):
    """app.js asks for source-layer "bands"; a renamed layer is a blank globe
    with no error. The archive's JSON metadata names its vector layers."""
    out = tmp_path / "t.pmtiles"
    tiles.write_pmtiles(SQUARE, out)
    assert f'"id":"{tiles.LAYER}"'.encode() in _metadata(out) or \
        f'"id": "{tiles.LAYER}"'.encode() in _metadata(out)


def _metadata(path) -> bytes:
    """The gzipped JSON metadata block a PMTiles v3 header points at."""
    import gzip
    import struct

    head = path.read_bytes()[:127]
    # v3 header: magic[0:7], version[7], root dir offset/length at 8/16,
    # JSON metadata offset/length at 24/32, gzip when byte 97 == 2.
    meta_off, meta_len = struct.unpack_from("<QQ", head, 24)
    with open(path, "rb") as fh:
        fh.seek(meta_off)
        raw = fh.read(meta_len)
    return gzip.decompress(raw) if head[97] == 2 else raw


@needs_tippecanoe
def test_the_archive_is_published_by_rename_in_its_own_directory(monkeypatch, tmp_path):
    """shutil.move across filesystems is a copy plus unlink: the target was
    truncated for the seconds a 27 MB copy took, and a worker killed mid-copy
    left a partial archive the deploy gate accepted."""
    import os
    seen = []
    real = os.replace

    def spy(src, dst):
        seen.append((str(src), str(dst)))
        return real(src, dst)
    monkeypatch.setattr(os, "replace", spy)
    out = tmp_path / "t.pmtiles"
    tiles.write_pmtiles(SQUARE, out)
    publishes = [(s, d) for s, d in seen if d == str(out)]
    assert publishes, "the archive was not published with os.replace"
    src, _ = publishes[-1]
    assert str(tmp_path) == os.path.dirname(src), f"rename source {src} is not beside the target"


@needs_tippecanoe
def test_the_archive_metadata_carries_no_local_path(tmp_path):
    out = tmp_path / "seoul.pmtiles"
    tiles.write_pmtiles(SQUARE, out)
    meta = _metadata(out).decode()
    assert "/Users/" not in meta and "/var/folders" not in meta and "/tmp/" not in meta, meta[:300]
    assert '"name":"seoul"' in meta or '"name": "seoul"' in meta


def test_sweep_removes_only_files_whose_writer_is_gone(tmp_path):
    """The staging directory is shared by every build on the machine and by
    this suite: a sweep that deleted everything aborted another build's
    in-flight origin. Only a file whose pid is dead is stale."""
    import os
    import subprocess
    import sys

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    stale = tmp_path / f"seoul.{dead.pid}.abc.geojson"
    live = tmp_path / f"tokyo.{os.getpid()}.abc.geojson"
    foreign = tmp_path / "someone-elses.geojson"
    for p in (stale, live, foreign):
        p.write_text("{}")
    assert tiles.sweep_scratch(tmp_path) == 1
    assert not stale.exists() and live.exists() and foreign.exists()


def _band_collection():
    """A real band set on a refined grid that straddles the antimeridian
    (Taveuni, Fiji): every level of detail, wrapping and split cells, and
    multipolygons -- the shapes whose encoding could differ."""
    import h3
    import numpy as np

    from transport_maps import config
    from transport_maps.contour import bands, grid
    from transport_maps.graph import refine

    centre = h3.latlng_to_cell(-16.8, 180.0, config.SOLVE_RES)
    base = sorted(h3.grid_disk(centre, 4))
    split = [c for c in sorted(h3.grid_disk(centre, 1)) if bands._crosses_antimeridian(c)][:2]
    cells, base_index, fine = refine.refine(base, np.array([c in split for c in base]))

    class Idx:
        pass
    idx = Idx()
    idx.cells, idx.n_cells = cells, len(cells)
    idx.base_cells, idx.base_index, idx.fine = base, base_index, fine
    edges = np.asarray(config.BAND_EDGES_MIN, dtype=float)
    band = np.random.default_rng(3).integers(0, 9, size=len(cells))
    minutes = np.where(band == 0, 1.0, edges[np.maximum(band - 1, 0)] + 1.0)
    minutes[band == 8] = np.inf
    return bands.band_feature_collection(idx, minutes, grid=grid.universe(base),
                                         native=grid.native_edges(idx))


def test_tippecanoe_reads_the_same_bytes_the_whole_collection_dump_wrote(monkeypatch, tmp_path):
    """R1: the bands keep shapely geometries and `write_pmtiles` maps and
    encodes one feature at a time, instead of `json.dump` over a collection
    whose every geometry was already a `mapping()` -- several GB of nested
    tuples per origin. The file tippecanoe is handed must be byte for byte
    the one the old path wrote, or the tiles could change.

    The old path is rebuilt from the same geometries: `mapping()` on each,
    then one `json.dump`. tippecanoe itself is replaced by a stub that
    keeps its input.

    Mutations performed and reverted, each red: the writer's separator
    `", "` -> `","`; `shapely.to_geojson`'s text spliced in for the
    geometry (what the plan first proposed: same shapes, other bytes);
    contour.bands storing `mapping(geometry)` again (the memory half).
    """
    import io
    import json
    import subprocess
    from pathlib import Path

    from shapely.geometry import mapping
    from shapely.geometry.base import BaseGeometry

    fc = _band_collection()
    assert len(fc["features"]) > 10
    assert all(isinstance(f["geometry"], BaseGeometry) for f in fc["features"]), \
        "the bands are back to holding mapped geometry"
    assert any(f["geometry"].geom_type == "MultiPolygon" for f in fc["features"])

    old = io.StringIO()
    json.dump({**fc, "features": [{**f, "geometry": mapping(f["geometry"])}
                                  for f in fc["features"]]}, old)

    seen = {}

    def tippecanoe(cmd, **kw):
        cwd = Path(kw["cwd"])
        seen["input"] = (cwd / cmd[-1]).read_bytes()
        (cwd / cmd[cmd.index("-o") + 1]).write_bytes(b"PMTiles stub")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tiles.shutil, "which", lambda name: "/stub/tippecanoe")
    monkeypatch.setattr(tiles.subprocess, "run", tippecanoe)
    tiles.write_pmtiles(fc, tmp_path / "taveuni.pmtiles")

    assert seen["input"] == old.getvalue().encode()
    # A geometry that is already a mapping passes through unchanged.
    plain = io.StringIO()
    tiles.write_geojson(SQUARE, plain)
    assert plain.getvalue() == json.dumps(SQUARE)


def test_the_fast_mapping_encodes_exactly_as_shapely_mapping():
    """`_mapping` replaced `mapping()` for speed; json.dumps of the two must
    be the same string for every shape the bands make -- polygons with and
    without holes, multipolygons, the empty polygon -- and for anything else.

    Mutation performed and reverted: the rings of a part appended in reverse
    (`polys[part].insert(0, ...)`) -> red.
    """
    import json

    import shapely
    from shapely.geometry import MultiPolygon, Point, Polygon, mapping

    holed = (Point(127.0, 37.5).buffer(1.0).difference(Point(127.2, 37.4).buffer(0.2))
             .difference(Point(126.7, 37.7).buffer(0.1)))
    assert len(holed.interiors) == 2
    shapes = [holed, Point(0, 0).buffer(1), MultiPolygon([holed, Point(130, 35).buffer(0.5)]),
              Polygon(), shapely.box(0.1, 0.2, 0.30000000000000004, 1e-07), Point(1, 2)]
    for g in shapes:
        assert json.dumps(tiles._mapping(g)) == json.dumps(mapping(g)), g.geom_type
