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


def _line_pbf(path, *, relation=None, maxspeed="300", loops=True):
    """Main line w1 from 120.0 to 121.0 E with a loop near each end, stations
    A and B beside it. `relation` is a tags dict for a train relation over the
    line calling at A and B, or None for no relation."""
    n = round(1.0 / STEP) + 1
    main = [(1000 + i, LAT, 120.0 + i * STEP) for i in range(n)]
    nodes = list(main)
    nodes += [(1, LAT + 0.002, 120.003, {"railway": "station", "name": "A"}),
              (2, LAT + 0.002, 120.997, {"railway": "station", "name": "B"})]
    ways = [(1, [m[0] for m in main],
             {"railway": "rail", "highspeed": "yes", "maxspeed": maxspeed, "usage": "main"})]
    if loops:
        nodes += [(3, LAT + 0.0005, 120.003), (4, LAT + 0.0005, 120.997)]
        ways += [(2, [1001, 3, 1002], {"railway": "rail", "service": "siding", "highspeed": "yes"}),
                 (3, [1000 + n - 3, 4, 1000 + n - 2],
                  {"railway": "rail", "service": "siding", "highspeed": "yes"})]
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
