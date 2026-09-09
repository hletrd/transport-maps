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
