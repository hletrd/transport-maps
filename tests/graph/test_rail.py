"""Rail edge construction."""

import polars as pl
import pytest

from transport_maps.graph import rail
from transport_maps.sources.osm import SCHEMA


def frame(rows):
    return pl.DataFrame(rows, schema=SCHEMA)


def stop(route_id, seq, lat, lon, name, highspeed=False):
    return {"route_id": route_id, "seq": seq, "stop_id": route_id * 1000 + seq,
            "lat": lat, "lon": lon, "name": name, "highspeed": highspeed}


CAL = rail.RailCalibration(highspeed_kmh=200.0, conventional_kmh=75.0,
                           detour_factor=1.2, boarding_min=15.0, alighting_min=5.0)


def test_no_edge_is_created_between_two_different_routes():
    """The `seq` shift must be partitioned by route.

    Unpartitioned, the last stop of route 1 joins to the first of route 2 and
    invents a rail edge between two cities that share no track at all.
    """
    df = frame([stop(1, 0, 48.85, 2.35, "Paris"), stop(1, 1, 45.76, 4.84, "Lyon"),
                stop(2, 0, 35.68, 139.69, "Tokyo"), stop(2, 1, 34.69, 135.50, "Osaka")])
    e = rail.ride_edges(df, CAL)
    st = {n: rail.station_key(la, lo) for n, la, lo in
          (("Paris",48.85,2.35), ("Lyon",45.76,4.84),
           ("Tokyo",35.68,139.69), ("Osaka",34.69,135.50))}
    pairs = set(zip(e["from_station"], e["to_station"]))
    assert (st["Lyon"], st["Tokyo"]) not in pairs, "joined two unrelated routes"
    assert len(e) == 2


def test_highspeed_is_faster_than_conventional_over_the_same_distance():
    a, b = (48.85, 2.35), (45.76, 4.84)
    slow = rail.ride_edges(frame([stop(1, 0, *a, "A"), stop(1, 1, *b, "B")]), CAL)
    fast = rail.ride_edges(frame([stop(2, 0, *a, "A", True),
                                  stop(2, 1, *b, "B", True)]), CAL)
    assert fast["minutes"][0] < slow["minutes"][0]
    assert slow["minutes"][0] / fast["minutes"][0] == pytest.approx(200 / 75, rel=1e-6)


def test_platforms_metres_apart_collapse_to_one_station():
    """Otherwise a big interchange becomes dozens of stations with free hops."""
    df = frame([stop(1, 0, 48.8800, 2.3550, "Nord platform 1"),
                stop(1, 1, 48.88003, 2.35505, "Nord platform 2"),
                stop(1, 2, 45.76, 4.84, "Lyon")])
    assert len(rail.stations(df)) == 2
    # The zero-length hop between the two platforms must not become an edge.
    assert len(rail.ride_edges(df, CAL)) == 1


def test_the_fastest_service_on_a_shared_segment_wins():
    a, b = (48.85, 2.35), (45.76, 4.84)
    df = frame([stop(1, 0, *a, "A"), stop(1, 1, *b, "B"),
                stop(2, 0, *a, "A", True), stop(2, 1, *b, "B", True)])
    e = rail.ride_edges(df, CAL)
    assert len(e) == 1
    solo_fast = rail.ride_edges(frame([stop(9, 0, *a, "A", True),
                                       stop(9, 1, *b, "B", True)]), CAL)
    assert e["minutes"][0] == pytest.approx(solo_fast["minutes"][0])


def test_ride_time_is_plausible_against_a_published_timetable():
    """Paris-Lyon by TGV: 394 km of track, about 2 h non-stop."""
    df = frame([stop(1, 0, 48.85, 2.35, "Paris", True),
                stop(1, 1, 45.76, 4.84, "Lyon", True)])
    assert 90 <= rail.ride_edges(df, CAL)["minutes"][0] <= 160
