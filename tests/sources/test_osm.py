"""Rail route parsing, on PBFs built here so the expected answer is known."""

import osmium
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


@pytest.mark.parametrize("tags,tier", [
    # Both spellings of the high-speed assertion still reach the top tier.
    ({"highspeed": "yes"}, "high_speed"),
    ({"service": "high_speed"}, "high_speed"),
    ({"service": "highspeed"}, "high_speed"),
    # `highspeed=yes` PROMOTES regardless of what `service` says.
    ({"service": "regional", "highspeed": "yes"}, "high_speed"),
    # The four tiers the bulk of the world's relations fall into.
    ({"service": "regional"}, "regional"),
    ({"service": "commuter"}, "commuter"),
    ({"service": "long_distance"}, "long_distance"),
    ({"service": "tourism"}, "tourism"),
    # Folded synonyms, chosen on meaning and checked against observations.
    ({"service": "suburban"}, "commuter"),
    ({"service": "light_rail"}, "commuter"),
    ({"service": "national"}, "long_distance"),
    ({"service": "international"}, "long_distance"),
    ({"service": "tourist"}, "tourism"),
    # Absent, unrecognised, and whitespace/case noise all fall to default.
    ({}, "default"),
    ({"service": "night"}, "default"),
    ({"service": "car_shuttle"}, "default"),
    ({"service": "  "}, "default"),
    ({"service": "Regional"}, "regional"),
    # A `;`-joined value takes the SLOWEST tier it recognises, and ignores
    # tokens it does not.
    ({"service": "international;long_distance"}, "long_distance"),
    ({"service": "regional;international"}, "regional"),
    ({"service": "tourism;night;regional;long_distance"}, "tourism"),
    ({"service": "night;car"}, "default"),
])
def test_the_service_tag_selects_the_speed_tier(tmp_path, tags, tier):
    nodes = [(1, 40.0, 1.0, {"name": "A"}), (2, 41.0, 2.0, {"name": "B"})]
    rels = [(7, [("n", 1, "stop"), ("n", 2, "stop")], TRAIN | tags)]
    write_pbf(tmp_path / "h-rail.osm.pbf", nodes, rels)
    assert osm.rail_routes(extracts_dir=tmp_path)["tier"].to_list() == [tier, tier]


def test_every_tier_the_mapping_can_yield_is_one_the_calibration_prices():
    """`_TIER_BY_SERVICE` and `RAIL_TIERS` must not drift apart.

    A synonym mapped to a tier name with a typo would reach `ride_edges` and
    raise there, hours into a build, rather than here.
    """
    assert set(osm._TIER_BY_SERVICE.values()) <= set(osm.RAIL_TIERS)
    assert osm.DEFAULT_TIER in osm.RAIL_TIERS


def test_the_operator_and_ref_tags_are_carried_through_the_parse(tmp_path):
    """They are 92% and 88% covered worldwide and are what lets a leg read
    like a timetable instead of a guess."""
    nodes = [(1, 40.0, 1.0, {"name": "A"}), (2, 41.0, 2.0, {"name": "B"})]
    rels = [(7, [("n", 1, "stop"), ("n", 2, "stop")],
             TRAIN | {"operator": " Korail ", "ref": "101", "name": "KTX"})]
    write_pbf(tmp_path / "o-rail.osm.pbf", nodes, rels)
    df = osm.rail_routes(extracts_dir=tmp_path)
    assert df["operator"].to_list() == ["Korail", "Korail"], "must be stripped"
    assert df["ref"].to_list() == ["101", "101"]
    assert df["route_name"].to_list() == ["KTX", "KTX"]


def test_a_stop_with_no_name_stays_empty_rather_than_taking_the_route_name(tmp_path):
    """It used to inherit the relation's `name`, and `emit/rail_detail` then
    published the LINE as the station: 1,144 of 124,488 shipped rows read
    `via S1: Rostock Hbf -> Warnemünde (S1: Rostock Hbf -> Warnemünde)`."""
    nodes = [(1, 40.0, 1.0, {"name": "Named"}), (2, 41.0, 2.0, {})]
    rels = [(7, [("n", 1, "stop"), ("n", 2, "stop")],
             TRAIN | {"name": "S1: Rostock Hbf -> Warnemünde"})]
    write_pbf(tmp_path / "n-rail.osm.pbf", nodes, rels)
    df = osm.rail_routes(extracts_dir=tmp_path).sort("seq")
    assert df["name"].to_list() == ["Named", ""]


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
    # The two extracts are the same size, so the fingerprint's moving part is
    # the mtime; on a coarse-mtime filesystem a rewrite within one tick would
    # look unchanged. Make the miss by construction.
    import os
    t_ns = os.stat(p).st_mtime_ns + 1_000_000_000
    os.utime(p, ns=(t_ns, t_ns))
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


def test_a_cross_border_route_keeps_one_extract_whole_never_spliced():
    """A route in two regional extracts must keep ONE extract's sequence.

    `_parse` renumbers `seq` from 0 per extract, so the previous merge --
    which counted rows per route_id over the concatenation of both, making the
    "longer one wins" sort a no-op -- kept whichever row of each seq came
    first and interleaved the two truncated sequences. Measured on the shipped
    cache: 1,823 duplicated (route_id, stop_id) pairs across 469 routes, 891
    routes with a >200 km "consecutive" hop, max 6,351 km.
    """
    import polars as pl

    from transport_maps.sources import osm

    def rows(extract, route, stops):
        return [{"route_id": route, "seq": i, "stop_id": s, "lat": 0.0, "lon": float(s),
                 "name": f"stop{s}", "tier": "default", "route_name": "R",
                 "operator": "", "ref": "", "_extract": extract} for i, s in enumerate(stops)]

    df = pl.DataFrame(
        rows("east.osm.pbf", 1, [10, 11]) + rows("west.osm.pbf", 1, [20, 21, 22, 23]),
        schema={**osm.SCHEMA, "_extract": pl.Utf8})
    out = osm._pick_one_extract_per_route(df)

    assert out["stop_id"].to_list() == [20, 21, 22, 23], "the longer extract must win, whole"
    assert out["seq"].to_list() == [0, 1, 2, 3], "seq stays gapless"
    assert out.height == out.select(["route_id", "seq"]).unique().height


def test_no_route_carries_two_extracts_stops():
    """Forty cross-border routes at once.

    One route is not enough to prove this: the old merge's `sort("_n")` had
    nothing to order by, and polars does not promise a stable sort, so a
    single route could come out right by luck. Across forty the old code
    interleaves, and the invariant -- every route's stops come from exactly
    one extract -- is what the shipped cache violates on 469 real routes.
    """
    import polars as pl

    from transport_maps.sources import osm

    rows = []
    for route in range(40):
        for extract, base, n in (("east.pbf", 1000, 3), ("west.pbf", 2000, 5)):
            for i in range(n):
                rows.append({"route_id": route, "seq": i, "stop_id": base + route * 10 + i,
                             "lat": 0.0, "lon": 0.0, "name": "x", "tier": "default",
                             "route_name": "R", "operator": "", "ref": "",
                             "_extract": extract})
    out = osm._pick_one_extract_per_route(
        pl.DataFrame(rows, schema={**osm.SCHEMA, "_extract": pl.Utf8}))

    assert out.height == 40 * 5, "the five-stop extract wins every route, whole"
    for route in range(40):
        stops = out.filter(pl.col("route_id") == route)["stop_id"].to_list()
        assert all(s >= 2000 for s in stops), f"route {route} mixes extracts: {stops}"
        assert stops == sorted(stops) and len(set(stops)) == len(stops)


def test_a_tie_is_broken_by_extract_name_not_by_directory_order():
    import polars as pl

    from transport_maps.sources import osm

    def frame(order):
        return pl.DataFrame(
            [{"route_id": 3, "seq": i, "stop_id": s, "lat": 0.0, "lon": 0.0, "name": "x",
              "tier": "default", "route_name": "R", "operator": "", "ref": "",
              "_extract": e}
             for e, stops in order for i, s in enumerate(stops)],
            schema={**osm.SCHEMA, "_extract": pl.Utf8})

    a = osm._pick_one_extract_per_route(frame([("alpha.pbf", [1, 2]), ("beta.pbf", [3, 4])]))
    b = osm._pick_one_extract_per_route(frame([("beta.pbf", [3, 4]), ("alpha.pbf", [1, 2])]))
    assert a["stop_id"].to_list() == b["stop_id"].to_list() == [1, 2]


def test_the_parser_version_is_in_the_rail_cache_key():
    """A cache built by the splicing parser must be a MISS, not a silent reuse."""
    from transport_maps.sources import osm

    fp = [("dir", "x-rail.osm.pbf", 1, 2)]
    before = osm._rail_cache_path(fp)
    original = osm.RAIL_PARSER_VERSION
    try:
        osm.RAIL_PARSER_VERSION = original + 1
        assert osm._rail_cache_path(fp) != before
    finally:
        osm.RAIL_PARSER_VERSION = original
