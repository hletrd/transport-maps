"""sources/gtfs_rail: rail legs timed from open GTFS timetables."""

from __future__ import annotations

import zipfile

import polars as pl

from transport_maps.graph import rail
from transport_maps.sources import gtfs_rail


def _feed(tmp_path):
    """Stations A, B (two platforms under a parent), C; two trips A-B-C, the
    first faster, whose train dwells 8 min at A and 2 at B; a bus to ignore."""
    files = {
        "agency.txt": "agency_id,agency_name\n1,DB Fernverkehr AG\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nr,1,ICE,2\nbus,1,SEV,3\n",
        "stops.txt": ("stop_id,stop_name,stop_lat,stop_lon,parent_station,location_type\n"
                      "a,A Hbf,52.50,13.30,,\n"
                      "pb,\"B, B Hbf\",52.80,12.00,,1\n"
                      "b1,B Hbf,52.801,12.001,pb,\n"
                      "b2,B Hbf,52.802,12.002,pb,\n"
                      "c,C Hbf,53.55,10.00,,\n"),
        "trips.txt": "trip_id,route_id,trip_short_name\nfast,r,28\nslow,r,26\nsev,bus,1\n",
        "stop_times.txt": ("trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                           "fast,09:52:00,10:00:00,a,1\n"
                           "fast,10:30:00,10:31:00,b1,2\n"
                           "fast,10:31:00,10:32:00,b2,3\n"
                           "fast,11:00:00,11:00:00,c,4\n"
                           "slow,23:52:00,24:00:00,a,1\n"
                           "slow,24:40:00,24:42:00,b1,2\n"
                           "slow,25:20:00,25:20:00,c,3\n"
                           "sev,10:00:00,10:00:00,a,1\n"
                           "sev,10:05:00,10:05:00,c,2\n"),
    }
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return path


def test_every_pair_of_calls_is_timed_from_departure_to_arrival(tmp_path):
    """Boarding at A rides from A's DEPARTURE (the 8 min dwell there is not
    the traveller's); a ride through B pays B's dwell; the two platforms of B
    are one call; of two trips on one pattern each leg takes the faster; the
    bus is not a train; times past 24:00 continue the day.

    Mutations performed and reverted, each RED: time legs arrival-to-arrival
    (A->C reads 68); keep the first platform's departure at B (B->C reads 29).
    """
    (pat,) = gtfs_rail.patterns(_feed(tmp_path))
    assert [s[1] for s in pat["stops"]] == ["A Hbf", "B Hbf", "C Hbf"]
    assert pat["stops"][1][:1] == ("pb",)
    assert pat["minutes"] == {(0, 1): 30.0, (0, 2): 60.0, (1, 2): 28.0}
    assert pat["trips"] == 2 and pat["operator"] == "DB Fernverkehr AG"


def test_a_feed_supersedes_its_operators_relations_at_its_tiers_only():
    """Korail runs Seoul's commuter lines too, which its feed does not carry.

    Mutation performed and reverted: drop the tier test -> RED (the commuter
    relation is dropped).
    """
    df = pl.DataFrame({"operator": ["DB Fernverkehr AG", "DB Regio", "한국철도공사",
                                    "한국철도공사", None],
                       "tier": ["high_speed", "regional", "commuter", "high_speed",
                                "long_distance"]})
    assert gtfs_rail.superseded(df).to_list() == [True, False, False, True, False]


def _row(rid, seq, lat, lon, name, tier="regional", **kw):
    return {"route_id": rid, "seq": seq, "stop_id": rid * 10 + seq, "lat": lat, "lon": lon,
            "name": name, "tier": tier, "route_name": "", "operator": "", "ref": "", **kw}


def test_a_timed_leg_wins_its_pair_and_one_train_is_one_leg():
    """An OSM price between two timed stations does not undercut the
    timetable; a timed leg arrives at the alight-only twin, which no ride
    leaves, so two timed trains do not chain for free.

    Mutations performed and reverted, each RED: drop the `_covered` filter
    (the OSM A->B price survives); arrive at the plain station (a ride edge
    leaves B's arrival).
    """
    a, b, c = (52.50, 13.30), (52.80, 12.00), (53.55, 10.00)
    osm_ab = [_row(1, 0, *a, "A", tier="high_speed"), _row(1, 1, *b, "B", tier="high_speed")]
    timed = [_row(-2, 0, *a, "A", timetabled_min=40.0, alight_only=False),
             _row(-2, 1, *b, "B", alight_only=True),
             _row(-3, 0, *b, "B", timetabled_min=30.0, alight_only=False),
             _row(-3, 1, *c, "C", alight_only=True)]
    routes = pl.DataFrame(osm_ab + timed)
    edges = rail.ride_edges(routes, rail.load_rail_calibration())
    ka, kb, kc = (rail.station_key(*p) for p in (a, b, c))
    got = {(r["from_station"], r["to_station"]): r["minutes"] for r in edges.iter_rows(named=True)}
    assert got == {(ka, kb + rail.ALIGHT_SUFFIX): 40.0, (kb, kc + rail.ALIGHT_SUFFIX): 30.0}
    assert set(rail.stations(routes)["station"]) == {
        ka, kb, kc, ka + rail.ALIGHT_SUFFIX, kb + rail.ALIGHT_SUFFIX, kc + rail.ALIGHT_SUFFIX}


def test_rides_run_back_into_the_other_twin():
    """The graph makes every ride two-way (`rail.two_way`). Reversed naively a
    timed A -> B~a is B~a -> A, a ride leaving an alighting twin, from which a
    second train continues with no change paid; reversed OSM B -> A would
    undercut the timetable; and two stops in one station are no ride (the
    zero-weight edge the build refused).

    Mutations performed and reverted, each RED: reverse into the plain
    station; drop the anti-join on timed pairs; drop the one-station filter.
    """
    a, b, c = "a", "b", "c"
    x = rail.ALIGHT_SUFFIX
    edges = pl.DataFrame({"from_station": [a, b, b, a],
                          "to_station": [b + x, a, c, a + x],
                          "minutes": [40.0, 20.0, 30.0, 0.0]})
    got = {(r["from_station"], r["to_station"]): r["minutes"]
           for r in rail.two_way(edges).iter_rows(named=True)}
    assert got == {(a, b + x): 40.0, (b, a + x): 40.0, (b, c): 30.0, (c, b): 30.0}
    assert rail.reverse_ride(a, b + x) == (b, a + x)


def _zip(path, files, folder=""):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(folder + name, text)
    return path


def _mixed_feed(tmp_path, folder=""):
    """A national feed's shape: a TGV and a TER over the same stations, told
    apart only by their stop ids (SNCF's export), the TGV calling once at a
    stop stops.txt does not list (Amtrak's "OSM") and once with no time (VIA's
    request stops)."""
    stops = "stop_id,stop_name,stop_lat,stop_lon,parent_station\n"
    for cat in ("TGV INOUI", "Train TER"):
        stops += "".join(f"StopPoint:OCE{cat}-{k},{n},{lat},{lon},\n"
                         for k, n, lat, lon in (("1", "Paris", 48.84, 2.37),
                                                ("2", "Dijon", 47.32, 5.03),
                                                ("3", "Lyon", 45.76, 4.86)))
    files = {
        "agency.txt": "agency_id,agency_name\n1187,SNCF VOYAGEURS\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nr,1187,K7,2\n",
        "stops.txt": stops,
        "trips.txt": "trip_id,route_id\ntgv,r\nter,r\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "tgv,07:00:00,07:00:00,StopPoint:OCETGV INOUI-1,1\n"
            "tgv,08:30:00,08:31:00,OSM,2\n"
            "tgv,,,StopPoint:OCETGV INOUI-2,3\n"
            "tgv,09:00:00,09:00:00,StopPoint:OCETGV INOUI-3,4\n"
            "ter,07:00:00,07:00:00,StopPoint:OCETrain TER-1,1\n"
            "ter,09:00:00,09:05:00,StopPoint:OCETrain TER-2,2\n"
            "ter,11:00:00,11:00:00,StopPoint:OCETrain TER-3,3\n"),
    }
    return _zip(tmp_path / f"mixed{len(folder)}.zip", files, folder)


def test_a_feed_takes_only_the_trains_its_select_names(tmp_path):
    """SNCF's feed carries every TER; `select` keeps the TGV at its tier, a
    call at an unlisted stop or with no time is skipped, and a feed packed in
    a folder (ÖBB's GTFS_Fahrplan_2026/) reads the same.

    Mutations performed and reverted, each RED: `tier_of` ignoring `select`
    (the TER is taken too); `_member` looking at the archive root only
    (KeyError on the folder feed); not skipping the unlisted stop (KeyError);
    not skipping the untimed call (ValueError).
    """
    feed = {"name": "x", "tier": "high_speed",
            "select": (("stop_id", r"^StopPoint:OCETGV INOUI-", "high_speed"),
                       ("stop_id", r"^StopPoint:OCEINTERCITES-", "long_distance"))}
    for folder in ("", "GTFS_Fahrplan_2026/"):
        (pat,) = gtfs_rail.patterns(_mixed_feed(tmp_path, folder), feed)
        assert [s[1] for s in pat["stops"]] == ["Paris", "Lyon"]
        assert pat["tier"] == "high_speed" and pat["minutes"] == {(0, 1): 120.0}
    # Without `select`, every train at the feed's own tier.
    pats = gtfs_rail.patterns(_mixed_feed(tmp_path), {"tier": "regional"})
    assert len(pats) == 2 and {p["tier"] for p in pats} == {"regional"}


def test_select_rules_are_ordered_and_a_none_tier_refuses():
    """Mutation performed and reverted: return the LAST matching rule's tier
    -> RED (RJX 162 reads None)."""
    feed = {"tier": "long_distance",
            "select": (("trip_short_name", r"^RJX ", "high_speed"),
                       ("trip_short_name", r"^RJ", None),
                       ("route_type", r"^10[23]$", "long_distance"))}
    assert gtfs_rail.tier_of(feed, {"trip_short_name": "RJX 162"}) == "high_speed"
    assert gtfs_rail.tier_of(feed, {"trip_short_name": "RJ 658", "route_type": "102"}) is None
    assert gtfs_rail.tier_of(feed, {"trip_short_name": "IC 5", "route_type": "103"}) == \
        "long_distance"
    assert gtfs_rail.tier_of(feed, {"trip_short_name": "S 3", "route_type": "109"}) is None

