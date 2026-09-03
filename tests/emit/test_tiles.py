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


def test_writes_a_non_empty_pmtiles_file(tmp_path):
    out = tmp_path / "t.pmtiles"
    tiles.write_pmtiles(SQUARE, out)
    assert out.stat().st_size > 0
    assert out.read_bytes()[:7] == b"PMTiles"
