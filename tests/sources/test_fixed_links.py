"""Bridges and tunnels read from OSM: which ways count, and when the set is usable."""

import h3
import osmium
import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import fixed_links as fl


@pytest.mark.parametrize("tags,expected", [
    ({"bridge": "yes", "highway": "primary"}, "highway"),
    ({"tunnel": "yes", "railway": "rail"}, "railway"),
    ({"bridge": "viaduct", "railway": "subway"}, "railway"),
    ({"bridge": "yes", "highway": "footway"}, "highway"),       # walkable is joined
    ({"bridge": "no", "highway": "primary"}, None),             # an explicit denial
    ({"highway": "primary"}, None),                             # an ordinary road
    ({"bridge": "yes", "waterway": "canal"}, None),             # an aqueduct carries water
    ({"bridge": "yes", "highway": "proposed"}, None),           # not built
    ({"tunnel": "yes", "railway": "abandoned"}, None),          # no longer carries anything
    ({"bridge": "yes", "highway": "construction"}, None),
])
def test_only_a_bridge_or_tunnel_that_carries_traffic_counts(tags, expected):
    assert fl.carries_traffic(tags) == expected


def _write(path, nodes, ways):
    w = osmium.SimpleWriter(str(path))
    for nid, lat, lon in nodes:
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat), tags={}))
    for wid, refs, tags in ways:
        w.add_way(osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags))
    w.close()


# Helsinki: a 5.5 km span that crosses several FINE_RES cells, and a 5 m one.
LONG_A, LONG_B = (60.150, 24.950), (60.200, 24.950)
SHORT_A, SHORT_B = (60.150, 24.950), (60.15005, 24.950)


def test_the_parse_keeps_long_links_and_drops_everything_that_cannot_join_cells(tmp_path):
    assert h3.latlng_to_cell(*SHORT_A, fl.KEEP_RES) == h3.latlng_to_cell(*SHORT_B, fl.KEEP_RES), \
        "fixture: the short span must sit inside ONE fine cell, or it tests nothing"
    assert h3.latlng_to_cell(*LONG_A, fl.KEEP_RES) != h3.latlng_to_cell(*LONG_B, fl.KEEP_RES)
    pbf = tmp_path / "x.osm.pbf"
    _write(pbf,
           nodes=[(1, *LONG_A), (2, *LONG_B), (3, *SHORT_A), (4, *SHORT_B),
                  (5, *LONG_A), (6, *LONG_B), (7, *LONG_A), (8, *LONG_B)],
           ways=[(10, [1, 2], {"bridge": "yes", "highway": "primary", "name": "Long"}),
                 (11, [3, 4], {"bridge": "yes", "highway": "primary"}),     # one cell
                 (12, [5, 6], {"bridge": "no", "highway": "primary"}),      # denied
                 (13, [7, 8], {"highway": "primary"})])                     # no key
    rows = fl._links(pbf)
    assert [r["way_id"] for r in rows] == [10]
    assert rows[0]["kind"] == "highway" and rows[0]["name"] == "Long"
    assert rows[0]["lat"] == [LONG_A[0], LONG_B[0]]


def test_a_way_whose_nodes_are_missing_from_the_extract_is_dropped(tmp_path):
    """A way cut at an extract boundary references nodes that are not there."""
    pbf = tmp_path / "x.osm.pbf"
    _write(pbf, nodes=[(1, *LONG_A)],
           ways=[(10, [1, 99], {"bridge": "yes", "highway": "primary"})])
    assert fl._links(pbf) == []


def _cache_region(region, source_key="k"):
    df = pl.DataFrame([{"way_id": hash(region) % 10_000, "kind": "highway", "name": region,
                        "lat": [0.0, 0.1], "lon": [0.0, 0.1]}], schema=fl.SCHEMA)
    df.write_parquet(fl._cache_path(region, source_key))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    (tmp_path / "osm").mkdir()
    return tmp_path


def test_one_missing_region_returns_none_without_parsing_the_others(cache, monkeypatch):
    """Coverage is settled first. Parsing as it went, a missing Africa would be
    found only after hours on Asia and Europe, and the work thrown away.

    Every region but one has a raw extract here and none has a cache, so any
    parse at all would call `_links`.
    """
    for region in fl.REGIONS[1:]:
        (cache / "osm" / f"{region}.osm.pbf").write_bytes(b"not parsed")

    def boom(_path):
        raise AssertionError("parsed an extract with coverage incomplete")

    monkeypatch.setattr(fl, "_links", boom)
    assert fl.fixed_links() is None


def test_a_complete_set_of_caches_is_used_without_the_raw_extracts(cache):
    """The raw extracts are 70 GB; the caches must stand without them."""
    for region in fl.REGIONS:
        _cache_region(region)
    df = fl.fixed_links()
    assert df is not None and sorted(df["name"].to_list()) == sorted(fl.REGIONS)


def test_a_newer_download_is_a_cache_miss(cache, monkeypatch):
    """With the raw file present its exact source key must match; otherwise a
    re-download would be answered from the parse of the old one."""
    for region in fl.REGIONS:
        _cache_region(region, source_key="stale")
    raw = cache / "osm" / f"{fl.REGIONS[0]}.osm.pbf"
    raw.write_bytes(b"fresh")
    parsed = []
    monkeypatch.setattr(fl, "_links", lambda path: parsed.append(path) or [])
    fl.fixed_links()
    assert parsed == [raw], "the stale cache was read instead of parsing the new extract"
