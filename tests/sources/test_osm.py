"""Rail route parsing, on PBFs built here so the expected answer is known."""

import osmium
import polars as pl
import pytest

from transport_maps.sources import osm


def write_pbf(path, nodes, relations):
    w = osmium.SimpleWriter(str(path))
    for nid, lat, lon, tags in nodes:
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat), tags=tags))
    for rid, members, tags in relations:
        w.add_relation(osmium.osm.mutable.Relation(id=rid, members=members, tags=tags))
    w.close()


TRAIN = {"type": "route", "route": "train", "name": "Test Line"}


@pytest.fixture
def extracts(tmp_path):
    """Stops are written in an order that DISAGREES with the relation order.

    Node ids ascend west to east; the relation lists them east to west. Any
    implementation that sorted by id, by file order, or by geometry would come
    out reversed, so this fixture is what makes the ordering test meaningful.
    """
    nodes = [(10, 48.0, 2.0, {"railway": "station", "name": "West"}),
             (11, 48.0, 6.0, {"railway": "station", "name": "Mid"}),
             (12, 48.0, 9.0, {"railway": "station", "name": "East"})]
    rels = [(100, [("n", 12, "stop"), ("n", 11, "stop"), ("n", 10, "stop")], TRAIN)]
    write_pbf(tmp_path / "a-rail.osm.pbf", nodes, rels)
    return tmp_path


def test_stop_order_follows_relation_membership_not_geometry(extracts):
    df = osm.rail_routes(extracts_dir=extracts)
    assert df["name"].to_list() == ["East", "Mid", "West"]
    assert df["seq"].to_list() == [0, 1, 2]


def test_platform_roles_are_used_when_no_stop_roles_exist(tmp_path):
    nodes = [(1, 40.0, 1.0, {"name": "A"}), (2, 41.0, 2.0, {"name": "B"})]
    rels = [(7, [("n", 1, "platform"), ("n", 2, "platform")], TRAIN)]
    write_pbf(tmp_path / "p-rail.osm.pbf", nodes, rels)
    assert osm.rail_routes(extracts_dir=tmp_path)["name"].to_list() == ["A", "B"]


def test_unresolvable_stops_are_dropped_and_seq_stays_gapless(tmp_path):
    """A route crossing the extract boundary names nodes the file lacks.

    Leaving a gap in `seq` would make consecutive rows look adjacent when a
    station between them is missing, which later becomes a bogus rail edge.
    """
    nodes = [(1, 40.0, 1.0, {"name": "A"}), (3, 42.0, 3.0, {"name": "C"})]
    rels = [(7, [("n", 1, "stop"), ("n", 2, "stop"), ("n", 3, "stop")], TRAIN)]
    write_pbf(tmp_path / "g-rail.osm.pbf", nodes, rels)
    df = osm.rail_routes(extracts_dir=tmp_path)
    assert df["name"].to_list() == ["A", "C"]
    assert df["seq"].to_list() == [0, 1]


def test_a_route_left_with_one_stop_is_dropped(tmp_path):
    nodes = [(1, 40.0, 1.0, {"name": "A"})]
    rels = [(7, [("n", 1, "stop"), ("n", 2, "stop")], TRAIN),
            (8, [("n", 1, "stop"), ("n", 1, "stop")], TRAIN)]
    write_pbf(tmp_path / "s-rail.osm.pbf", nodes, rels)
    assert 7 not in osm.rail_routes(extracts_dir=tmp_path)["route_id"].to_list()


@pytest.mark.parametrize("tags", [{"highspeed": "yes"}, {"service": "high_speed"}])
def test_both_highspeed_spellings_are_recognised(tmp_path, tags):
    nodes = [(1, 40.0, 1.0, {"name": "A"}), (2, 41.0, 2.0, {"name": "B"})]
    rels = [(7, [("n", 1, "stop"), ("n", 2, "stop")], TRAIN | tags)]
    write_pbf(tmp_path / "h-rail.osm.pbf", nodes, rels)
    assert osm.rail_routes(extracts_dir=tmp_path)["highspeed"].to_list() == [True, True]


def test_non_train_routes_are_ignored(tmp_path):
    nodes = [(1, 40.0, 1.0, {"name": "A"}), (2, 41.0, 2.0, {"name": "B"})]
    bus = {"type": "route", "route": "bus", "name": "Bus 1"}
    write_pbf(tmp_path / "b-rail.osm.pbf", nodes,
              [(7, [("n", 1, "stop"), ("n", 2, "stop")], bus)])
    with pytest.raises(RuntimeError, match="no train routes"):
        osm.rail_routes(extracts_dir=tmp_path)


def test_missing_extracts_are_an_error_not_an_empty_frame(tmp_path):
    with pytest.raises(FileNotFoundError, match="no .*-rail.osm.pbf"):
        osm.rail_routes(extracts_dir=tmp_path)


def test_replacing_an_extract_of_the_same_name_is_a_cache_miss(tmp_path):
    """The parquet cache lives outside tmp_path, so its key must cover content.

    Keying on filenames alone made every test after the first read the first
    one's parquet -- the ordering test above passed even with the ordering
    deliberately broken. A re-downloaded extract has the same name and new
    contents, and must not silently reuse the old result.
    """
    p = tmp_path / "same-name-rail.osm.pbf"
    write_pbf(p, [(1, 40.0, 1.0, {"name": "A"}), (2, 41.0, 2.0, {"name": "B"})],
              [(7, [("n", 1, "stop"), ("n", 2, "stop")], TRAIN)])
    assert osm.rail_routes(extracts_dir=tmp_path)["name"].to_list() == ["A", "B"]

    p.unlink()
    write_pbf(p, [(1, 40.0, 1.0, {"name": "X"}), (2, 41.0, 2.0, {"name": "Y"})],
              [(7, [("n", 1, "stop"), ("n", 2, "stop")], TRAIN)])
    assert osm.rail_routes(extracts_dir=tmp_path)["name"].to_list() == ["X", "Y"], \
        "served a stale cache for a replaced extract"


def test_a_ferry_clipped_at_the_antimeridian_is_dropped(tmp_path):
    """An endpoint at exactly +/-180 is where the extract cut the way.

    Measuring to it turned one Pacific route into a pair of 4,800 km crossings
    -- the two longest "ferries" on Earth, both unnamed.
    """
    nodes = [(1, -36.8, -180.0, {}), (2, -25.1, -130.1, {}),
             (3, 35.9, -5.5, {}), (4, 44.4, 8.9, {})]
    ways = [(10, [1, 2], {"route": "ferry"}),          # clipped -> dropped
            (11, [3, 4], {"route": "ferry", "name": "Tanger-Genova"})]
    w = osmium.SimpleWriter(str(tmp_path / "f-rail.osm.pbf"))
    for nid, lat, lon, tags in nodes:
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat), tags=tags))
    for wid, refs, tags in ways:
        w.add_way(osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags))
    w.close()

    df = osm.ferry_links(extracts_dir=tmp_path)
    assert df["way_id"].to_list() == [11], "kept a way clipped at the antimeridian"
