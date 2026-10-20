"""sources/gtfs_rail: rail legs timed from open GTFS timetables."""

from __future__ import annotations

import itertools
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



def test_a_feed_whose_clock_abroad_is_wrong_drops_those_calls(tmp_path):
    """OVapi's London calls are in London's clock on some trips: with
    `drop_other_zones` they are not timed, and the calls at home still are.

    Mutation performed and reverted: ignore `drop_other_zones` -> RED (a
    22-min London -> Lille leg is timed)."""
    files = {
        "agency.txt": "agency_id,agency_name,agency_timezone\nIFF,NS International,"
                      "Europe/Amsterdam\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nr,IFF,Eurostar,2\n",
        "stops.txt": ("stop_id,stop_name,stop_lat,stop_lon,parent_station,stop_timezone\n"
                      "ldn,London St. Pancras Int.,51.53,-0.13,,Europe/London\n"
                      "lil,Lille Europe,50.64,3.08,,\n"
                      "bru,Brussel-Zuid,50.84,4.34,,Europe/Amsterdam\n"),
        "trips.txt": "trip_id,route_id\nt,r\n",
        "stop_times.txt": ("trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                           "t,13:04:00,13:04:00,ldn,1\nt,13:26:00,13:30:00,lil,2\n"
                           "t,14:05:00,14:05:00,bru,3\n"),
    }
    path = _zip(tmp_path / "ovapi.zip", files)
    (pat,) = gtfs_rail.patterns(path, {"tier": "high_speed", "drop_other_zones": True})
    assert [s[1] for s in pat["stops"]] == ["Lille Europe", "Brussel-Zuid"]
    assert pat["minutes"] == {(0, 1): 35.0}
    (pat,) = gtfs_rail.patterns(path, {"tier": "high_speed"})
    assert pat["minutes"][(0, 1)] == 22.0     # what the feed says, untrusted


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


def test_published_trains_are_timed_like_a_feed_and_join_the_timetables(monkeypatch):
    """A published train is every pair of its calls, departure(i) ->
    arrival(j), past midnight included, arriving at the alighting twin; and
    `with_timetables` carries the table beside the feeds.

    Mutations performed and reverted, each RED: time pairs arrival(i) ->
    arrival(j) (A->B reads 62); drop the carry for a midnight passed between
    calls (T 2's C reads 20); drop the carry for one passed in a dwell (B->C
    reads -1380);
    leave the table out of `with_timetables` (no published row arrives).
    """
    from transport_maps.sources import rail_published as rp

    t = rp.PublishedTrain("Op", "T 1", "high_speed", (
        ("A", 35.0, 139.0, "", "23:00"),
        ("B", 35.5, 138.0, "23:58", "00:01"),
        ("C", 36.0, 137.0, "00:40", "")), "https://example.org/t1", "2026-10-20")
    df = rp.rows((t,))
    board = df.filter(pl.col("seq") == 0).sort("timetabled_min")
    got = {(r["name"], df.filter((pl.col("route_id") == r["route_id"]) & (pl.col("seq") == 1))
            ["name"][0]): r["timetabled_min"] for r in board.iter_rows(named=True)}
    assert got == {("A", "B"): 58.0, ("B", "C"): 39.0, ("A", "C"): 100.0}
    assert df.filter(pl.col("seq") == 1)["alight_only"].all()
    assert df["route_id"].n_unique() == 3
    # Midnight passed on the line, not in a dwell: 23:52 departure, 00:20 arrival.
    late = rp.PublishedTrain("Op", "T 2", "high_speed", (
        ("A", 35.0, 139.0, "", "23:30"), ("B", 35.5, 138.0, "23:50", "23:52"),
        ("C", 36.0, 137.0, "00:20", "")), "https://example.org/t2", "2026-10-20")
    assert rp.call_minutes(late) == [(1410.0, 1410.0), (1430.0, 1432.0), (1460.0, 1460.0)]

    monkeypatch.setattr(gtfs_rail, "timetable_rows", lambda: rp.rows(()))
    monkeypatch.setattr(rp, "TRAINS", (t,))
    osm_routes = pl.DataFrame([_row(1, 0, 35.0, 139.0, "A"), _row(1, 1, 36.0, 137.0, "C")])
    out = gtfs_rail.with_timetables(osm_routes)
    assert out.filter(pl.col("timetabled_min").is_not_null())["timetabled_min"].sort().to_list() \
        == [39.0, 58.0, 100.0]


def test_every_published_train_cites_its_page_and_runs_forward():
    """The table's own rows: a source URL and a date on each, calls in time
    order (every pair positive), first arrival and last departure empty."""
    from transport_maps.sources import rail_published as rp

    assert rp.TRAINS
    for t in rp.TRAINS:
        assert t.source.startswith("https://") and t.checked
        assert t.calls[0][3] == "" and t.calls[-1][4] == ""
        times = rp.call_minutes(t)
        assert all(b[0] > a[1] for a, b in itertools.pairwise(times)), t.train
    df = rp.rows()
    assert (df.filter(pl.col("seq") == 0)["timetabled_min"] > 0).all()
    assert df["route_id"].n_unique() == len(df) // 2


def test_a_timing_abroad_sits_beside_osm_and_one_at_home_replaces_it():
    """SBB's EC from Florence to Bologna (72 min) was the only timing of that
    pair and erased OSM's 37-min Frecciarossa: a leg that does not `cover`
    its pair is one more service, in both directions.

    Mutations performed and reverted, each RED: `ride_edges` dropping OSM
    under any timed leg (A->B reads only 72); `two_way` anti-joining on any
    timed pair (B->A loses the 37)."""
    a, b = (43.78, 11.25), (44.51, 11.34)
    osm_ab = [_row(1, 0, *a, "A", tier="high_speed"), _row(1, 1, *b, "B", tier="high_speed")]
    ec = [_row(-2, 0, *a, "A", timetabled_min=72.0, alight_only=False, covers=False),
          _row(-2, 1, *b, "B", alight_only=True, covers=False)]
    cal = rail.load_rail_calibration()
    ka, kb = rail.station_key(*a), rail.station_key(*b)
    x = rail.ALIGHT_SUFFIX
    edges = rail.ride_edges(pl.DataFrame(osm_ab + ec), cal)
    got = {(r["from_station"], r["to_station"]): r["minutes"] for r in edges.iter_rows(named=True)}
    assert got[(ka, kb + x)] == 72.0 and (ka, kb) in got and got[(ka, kb)] < 72.0
    back = {(r["from_station"], r["to_station"]) for r in rail.two_way(edges).iter_rows(named=True)}
    assert {(kb, ka), (kb, ka + x)} <= back
    # The same leg at home covers the pair: OSM's price goes, both ways.
    home = [{**r, "covers": True} for r in ec]
    edges = rail.ride_edges(pl.DataFrame(osm_ab + home), cal)
    assert set(zip(edges["from_station"], edges["to_station"])) == {(ka, kb + x)}
    both = rail.two_way(edges)
    back = set(zip(both["from_station"], both["to_station"], strict=True))
    assert back == {(ka, kb + x), (kb, ka + x)}


def test_a_leg_covers_its_pair_when_one_end_is_in_its_feeds_home(monkeypatch):
    """Mutation performed and reverted: require BOTH ends at home -> RED (the
    Zurich -> Milan EC no longer covers)."""
    from transport_maps.sources import countries

    def country(cells):
        import h3
        return [("CHE" if h3.cell_to_latlng(c)[0] > 45.8 else "ITA") for c in cells]

    monkeypatch.setattr(countries, "cell_country", country)
    monkeypatch.setattr(gtfs_rail, "FEEDS", ({"name": "ch", "home": ("CHE",)},))

    def leg(rid, p, q, feed):
        return [{"route_id": rid, "seq": 0, "lat": p[0], "lon": p[1], "feed": feed},
                {"route_id": rid, "seq": 1, "lat": q[0], "lon": q[1], "feed": feed}]
    zur, mil, fir, bol = (47.38, 8.54), (45.49, 9.20), (43.78, 11.25), (44.51, 11.34)
    df = pl.DataFrame(leg(1, zur, mil, "ch") + leg(2, fir, bol, "ch")
                      + leg(3, fir, bol, "published"))
    got = gtfs_rail.with_cover(df).group_by("route_id").agg(pl.col("covers").first())
    assert dict(zip(got["route_id"], got["covers"])) == {1: True, 2: False, 3: True}
