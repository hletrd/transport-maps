"""The track the relations do not describe: promotion and the track network.

Every case runs the real parser over a PBF written here, so the expected
answer is known: a 96 km high-speed line along 30 N between two stations,
each with a passing loop (the switches a station has and a viaduct does not).
"""

import osmium
import polars as pl
import pytest

from transport_maps.sources import osm, rail_track

LAT = 30.0
STEP = 0.002                      # node spacing along the line, degrees of longitude


def _line_pbf(path, *, relation=None, maxspeed="300", loops=True, highspeed=True):
    """Main line w1 from 120.0 to 121.0 E with a loop near each end, stations
    A and B beside it. `relation` is a tags dict for a train relation over the
    line calling at A and B, or None for no relation."""
    n = round(1.0 / STEP) + 1
    main = [(1000 + i, LAT, 120.0 + i * STEP) for i in range(n)]
    nodes = list(main)
    nodes += [(1, LAT + 0.002, 120.003, {"railway": "station", "name": "A"}),
              (2, LAT + 0.002, 120.997, {"railway": "station", "name": "B"})]
    hs = {"highspeed": "yes"} if highspeed else {}
    ways = [(1, [m[0] for m in main],
             {"railway": "rail", **hs, "maxspeed": maxspeed, "usage": "main"})]
    if loops:
        nodes += [(3, LAT + 0.0005, 120.003), (4, LAT + 0.0005, 120.997)]
        ways += [(2, [1001, 3, 1002], {"railway": "rail", "service": "siding", **hs}),
                 (3, [1000 + n - 3, 4, 1000 + n - 2],
                  {"railway": "rail", "service": "siding", **hs})]
    w = osmium.SimpleWriter(str(path))
    for node in nodes:
        nid, la, lo = node[:3]
        tags = node[3] if len(node) > 3 else {}
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(lo, la), tags=tags))
    for wid, refs, tags in ways:
        w.add_way(osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags))
    if relation is not None:
        members = [("n", 1, "stop"), ("n", 2, "stop"), ("w", 1, "")]
        w.add_relation(osmium.osm.mutable.Relation(
            id=500, members=members, tags={"type": "route", "route": "train", **relation}))
    w.close()


def _parse(tmp_path, **kw):
    _line_pbf(tmp_path / "x-rail.osm.pbf", **kw)
    return pl.DataFrame(osm._parse(tmp_path / "x-rail.osm.pbf"), schema=osm.SCHEMA)


@pytest.mark.parametrize("raw,kmh", [("300", 300.0), ("125 mph", 201.168), ("80 km/h", 80.0),
                                     ("signals", None), ("none", None), ("", None), ("3", None)])
def test_maxspeed_is_read_in_km_h(raw, kmh):
    """Mutation performed and reverted: drop the mph conversion -> RED."""
    got = rail_track.parse_maxspeed(raw)
    assert got == pytest.approx(kmh) if kmh else got is None


def test_an_untagged_relation_on_high_speed_track_is_high_speed(tmp_path):
    """Every Shinkansen relation carries no `service` tag and was priced at
    the default tier's 82 km/h. Its track says high-speed.

    Mutation performed and reverted: drop the promotion in `_parse` -> RED.
    """
    df = _parse(tmp_path, relation={"name": "Line"})
    rel = df.filter(pl.col("route_id") == 500)
    assert set(rel["tier"]) == {"high_speed"}
    assert rel["hs_share"][0] == pytest.approx(1.0)
    assert rel["vmax_kmh"][0] == pytest.approx(300.0)


def test_a_service_tag_is_never_overridden_by_the_track(tmp_path):
    """An S-Bahn tagged `commuter` on a 200 km/h line stops everywhere; the
    track does not make it an express.

    Mutation performed and reverted: promote whatever the tier -> RED.
    """
    df = _parse(tmp_path, relation={"name": "S1", "service": "commuter"})
    assert set(df.filter(pl.col("route_id") == 500)["tier"]) == {"commuter"}


def test_a_stopping_line_speed_is_not_high_speed(tmp_path):
    """Half the track high-speed is not enough when the line's own speed
    averages under 200: a German upgraded line's regional train."""
    assert rail_track.promotes(0.9, 300.0)
    assert not rail_track.promotes(0.9, 190.0)
    assert not rail_track.promotes(0.4, 300.0)
    assert rail_track.promotes(0.9, None)


def test_track_no_relation_runs_over_becomes_a_link_at_line_speed(tmp_path):
    """No relation: the line is built from the track. One link, A to B, the
    track's length and its time at 300 km/h.

    Mutations performed and reverted, each RED: require degree 4 for a switch
    (no stations, no link); take the line speed as 250 whatever `maxspeed`
    says.
    """
    df = _parse(tmp_path)
    links = df.filter(pl.col("route_id") < 0)
    assert links.height == 2 and sorted(links["name"]) == ["A", "B"]
    km = links["track_km"][0]
    assert km == pytest.approx(96.3, abs=1.5)
    assert links["line_h"][0] == pytest.approx(km / 300.0, rel=0.02)
    assert set(links["tier"]) == {"high_speed"}


def test_a_viaduct_past_a_station_is_not_a_stop(tmp_path):
    """No switches near the stations: the line passes them by."""
    assert _parse(tmp_path, loops=False).filter(pl.col("route_id") < 0).is_empty()


@pytest.mark.parametrize("tags", [{"name": "Line"}, {"name": "Avanti", "service": "long_distance"}])
def test_track_a_relation_runs_over_is_not_counted_twice(tmp_path, tags):
    """The relation prices A to B; an express link over the same track would
    make the line faster than either -- whatever the relation's tier: a UK
    125 mph main line is high-speed track run by `long_distance` relations.

    Mutations performed and reverted, each RED: build the network without
    leaving the covered ways out (both cases); cover only high-speed
    relations' ways (the second).
    """
    df = _parse(tmp_path, relation=tags)
    assert df.filter(pl.col("route_id") < 0).is_empty()
    assert df.filter(pl.col("route_id") == 500).height == 2


# ---- rebuild 33: each leg's own track, and the fast conventional lines -------

@pytest.mark.parametrize("tags,want", [
    ({"maxspeed": "200"}, (200.0, 200.0)),
    ({"maxspeed:forward": "160", "maxspeed:backward": "120"}, (160.0, 160.0)),
    ({"maxspeed": "110 mph", "maxspeed:tilting": "125 mph"}, (177.028, 201.168)),
    ({"maxspeed": "200", "maxspeed:tilting": "160"}, (200.0, 200.0)),
    ({"maxspeed:tilting": "200"}, (None, None)),
])
def test_a_ways_speed_reads_the_directional_and_tilting_tags(tags, want):
    """14,000 European ways carry only `maxspeed:forward`/`:backward`, and the
    WCML is 110 mph but 125 for a Pendolino.

    Mutations performed and reverted, each RED: drop the directional
    fallback; take `maxspeed:tilting` even where it is the lower.
    """
    got = rail_track.way_speeds(tags)
    assert got == (pytest.approx(want[0]) if want[0] else None,
                   pytest.approx(want[1]) if want[1] else None)


def _two_speed_pbf(path):
    """A long-distance relation A-M-B along 30 N: A to M on a 150 km/h way
    (200 for a tilting train), M to B on a 300 km/h one. The relation lists
    the second way first, and B is a station node 300 m off the line."""
    w = osmium.SimpleWriter(str(path))
    stop = {"railway": "stop", "public_transport": "stop_position"}
    for i in range(501):
        nid = 1000 + i
        tags = {**stop, "name": "A"} if nid == 1000 else {**stop, "name": "M"} if nid == 1250 else {}
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(120.0 + i * STEP, LAT), tags=tags))
    w.add_node(osmium.osm.mutable.Node(id=1, location=(121.0, LAT + 0.0027),
                                       tags={"railway": "station", "name": "B"}))
    w.add_way(osmium.osm.mutable.Way(id=1, nodes=list(range(1000, 1251)), tags={
        "railway": "rail", "maxspeed": "150", "maxspeed:tilting": "200", "usage": "main"}))
    w.add_way(osmium.osm.mutable.Way(id=2, nodes=list(range(1250, 1501)), tags={
        "railway": "rail", "maxspeed": "300", "usage": "main"}))
    members = [("n", 1000, "stop"), ("n", 1250, "stop"), ("n", 1, "stop"),
               ("w", 2, ""), ("w", 1, "")]
    w.add_relation(osmium.osm.mutable.Relation(id=500, members=members, tags={
        "type": "route", "route": "train", "service": "long_distance", "name": "IC"}))
    w.close()


def test_each_leg_carries_its_own_tracks_length_and_speed(tmp_path):
    """A relation is two lines at two speeds; each leg must say which.

    Mutations performed and reverted, each RED: place a stop anywhere on the
    chain rather than after the previous one; drop the nearest-node
    placement of a station beside the line; read the line speed for the
    tilting columns.
    """
    _two_speed_pbf(tmp_path / "x-rail.osm.pbf")
    df = pl.DataFrame(osm._parse(tmp_path / "x-rail.osm.pbf"), schema=osm.SCHEMA)
    rel = df.filter(pl.col("route_id") == 500).sort("seq")
    assert rel["name"].to_list() == ["A", "M", "B"]
    km = 0.5 * 96.3
    assert rel["leg_km"][:2].to_list() == pytest.approx([km, km], rel=0.02)
    assert rel["leg_line_h"][:2].to_list() == pytest.approx([km / 150, km / 300], rel=0.02)
    assert rel["leg_line_h_tilt"][:2].to_list() == pytest.approx([km / 200, km / 300], rel=0.02)
    assert rel["leg_unknown_km"][:2].to_list() == pytest.approx([0.0, 0.0], abs=0.01)


@pytest.mark.parametrize("maxspeed,links", [("180", 2), ("140", 0)])
def test_fast_conventional_track_no_relation_runs_over_is_a_long_distance_leg(
        tmp_path, maxspeed, links):
    """A 180 km/h main line OSM lists no train on becomes a `long_distance`
    link priced from its track by that tier's line terms -- not a
    high-speed express. Under 160 km/h it is left alone.

    Mutations performed and reverted, each RED: drop the fast network from
    `_parse`; price its links as an express (`line_h`); FAST_MIN_KMH 120.
    """
    df = _parse(tmp_path, maxspeed=maxspeed, highspeed=False)
    got = df.filter(pl.col("route_id") < 0).sort("seq")
    assert got.height == links
    if links:
        assert set(got["tier"]) == {"long_distance"}
        assert got["line_h"].is_null().all()
        assert got["leg_km"][0] == pytest.approx(96.3, abs=1.5)
        assert got["leg_line_h"][0] == pytest.approx(got["leg_km"][0] / 180.0, rel=0.02)
