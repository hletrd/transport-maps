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
