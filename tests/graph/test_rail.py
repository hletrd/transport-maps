"""Rail edge construction."""

import polars as pl
import pytest

from transport_maps.graph import rail
from transport_maps.sources.osm import SCHEMA


def frame(rows):
    return pl.DataFrame(rows, schema=SCHEMA)


def stop(route_id, seq, lat, lon, name, tier="default", route_name="",
         operator="", ref=""):
    """A stop row carrying EVERY column of `osm.SCHEMA`.

    It used to build seven keys against an eight-column schema, and polars
    filled the missing `route_name` with nulls in silence -- so the one column
    `emit/rail_detail` reads was never exercised by the fixture that claimed to
    model the parse. `test_the_fixture_covers_the_whole_schema` below now fails
    if a column is added to `SCHEMA` and not to this function.
    """
    return {"route_id": route_id, "seq": seq, "stop_id": route_id * 1000 + seq,
            "lat": lat, "lon": lon, "name": name, "tier": tier,
            "route_name": route_name, "operator": operator, "ref": ref}


def cal(**over):
    """A calibration whose six tiers are strictly ordered and all distinct.

    Distinct on BOTH terms: a test that only varied speed could not tell a
    missing `stop_overhead_min` from a present one.
    """
    tiers = {name: rail.RailTier(speed_kmh=kmh, stop_overhead_min=ovh)
             for name, (kmh, ovh) in (("tourism", (20.0, 0.5)),
                                      ("commuter", (74.0, 1.0)),
                                      ("default", (82.0, 1.5)),
                                      ("regional", (87.0, 2.0)),
                                      ("long_distance", (104.0, 3.0)),
                                      ("high_speed", (215.0, 5.0)))}
    return rail.RailCalibration(detour_factor=1.2, boarding_min=15.0,
                                alighting_min=5.0, tiers={**tiers, **over})


CAL = cal()


def test_the_fixture_covers_the_whole_schema():
    """`stop()` must name every column `osm.SCHEMA` declares.

    Without this, adding a column to the parse leaves every fixture in this
    file silently null in it -- which is exactly how `route_name` went
    untested from the day it was added.
    """
    built = set(stop(1, 0, 0.0, 0.0, "x"))
    assert built == set(SCHEMA), (
        f"fixture is missing {sorted(set(SCHEMA) - built)} and invents "
        f"{sorted(built - set(SCHEMA))}")


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


A_PARIS, B_LYON = (48.85, 2.35), (45.76, 4.84)
# Great-circle Paris-Lyon on a 6371.0088 km sphere, computed from the haversine
# formula written out by hand rather than imported from the module under test,
# so the expected minutes below are not the code restating itself.
PARIS_LYON_KM = 391.4891


def _one_leg(tier):
    return rail.ride_edges(
        frame([stop(1, 0, *A_PARIS, "A", tier), stop(1, 1, *B_LYON, "B", tier)]),
        CAL)["minutes"][0]


def test_the_SHIPPED_tiers_are_ordered_and_none_duplicates_another():
    """`RAIL_TIERS` is ordered slowest first and `calibration.toml` must agree.

    Added because a mutation proved it was needed: setting `commuter` to
    `regional`'s 86.7 km/h left every other test in this file green, because
    they all price against the fixture calibration. A tier that prices
    identically to its neighbour is a tier doing nothing, and the whole point
    of reading the `service` tag is that the tiers are distinguishable.
    """
    from transport_maps.sources.osm import RAIL_TIERS

    tiers = rail.load_rail_calibration().tiers
    speeds = [tiers[t].speed_kmh for t in RAIL_TIERS]
    assert speeds == sorted(speeds), dict(zip(RAIL_TIERS, speeds))
    assert len(set(speeds)) == len(RAIL_TIERS), (
        f"two shipped tiers price identically: {dict(zip(RAIL_TIERS, speeds))}")
    assert all(tiers[t].stop_overhead_min >= 0 for t in RAIL_TIERS)


def test_every_tier_is_strictly_faster_than_the_one_below_it():
    """The tiers exist to be distinguishable; if two price the same, one of
    them is not doing anything. `RAIL_TIERS` is ordered slowest first."""
    from transport_maps.sources.osm import RAIL_TIERS

    times = [_one_leg(t) for t in RAIL_TIERS]
    assert times == sorted(times, reverse=True), dict(zip(RAIL_TIERS, times))
    assert len(set(times)) == len(RAIL_TIERS), "two tiers price identically"


@pytest.mark.parametrize("tier", ["commuter", "regional", "high_speed"])
def test_a_leg_costs_its_tier_overhead_plus_its_tier_running_time(tier):
    """The exact figure, from the constants rather than from the code.

    This is what catches a dropped `stop_overhead_min`: without the term a
    commuter leg comes out at 381.2 min against the 382.2 asserted here, which
    no ordering assertion would notice.
    """
    t = CAL.tiers[tier]
    expected = t.stop_overhead_min + 60.0 * PARIS_LYON_KM * CAL.detour_factor / t.speed_kmh
    assert _one_leg(tier) == pytest.approx(expected, rel=1e-4)


def test_the_per_stop_overhead_is_charged_once_per_leg_not_once_per_route():
    """Two legs pay two overheads. Charging it per route would make a
    twenty-stop stopping service indistinguishable from a two-stop express."""
    mid = (47.30, 3.60)
    two = rail.ride_edges(frame([stop(1, 0, *A_PARIS, "A", "regional"),
                                 stop(1, 1, *mid, "M", "regional"),
                                 stop(1, 2, *B_LYON, "B", "regional")]), CAL)
    assert len(two) == 2
    ovh = CAL.tiers["regional"].stop_overhead_min
    # Each leg carries exactly one overhead, so the two legs' running time is
    # the total less two of them.
    assert float(two["minutes"].sum()) - 2 * ovh == pytest.approx(
        60.0 * PARIS_LYON_KM * CAL.detour_factor / CAL.tiers["regional"].speed_kmh,
        rel=0.02)


def test_a_tier_the_calibration_does_not_price_is_refused():
    """A null speed would become a NaN edge and a silently unreachable
    station, hours into a build, with no message naming the tier."""
    df = frame([stop(1, 0, *A_PARIS, "A", "monorail"),
                stop(1, 1, *B_LYON, "B", "monorail")])
    with pytest.raises(Exception, match="monorail"):
        rail.ride_edges(df, CAL)


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
                stop(2, 0, *a, "A", "high_speed"), stop(2, 1, *b, "B", "high_speed")])
    e = rail.ride_edges(df, CAL)
    assert len(e) == 1
    solo_fast = rail.ride_edges(frame([stop(9, 0, *a, "A", "high_speed"),
                                       stop(9, 1, *b, "B", "high_speed")]), CAL)
    assert e["minutes"][0] == pytest.approx(solo_fast["minutes"][0])


# The high-speed tier's own fitted residual: log-sd 0.156 over 57 observations,
# so one sigma is a factor of 1.169. The bound below is TWO sigma. It is not a
# round number chosen for comfort -- the window this replaced was 90 to 160
# minutes, which admitted a detour factor anywhere from 0.77 to 1.36 and would
# have passed with the `detour_factor` multiplication deleted entirely.
HIGH_SPEED_TWO_SIGMA = 1.169 ** 2


@pytest.mark.parametrize("name,km,legs,published_min", [
    # Seoul-Busan KTX: 2 h 15 published, 325 km great-circle, calling at
    # Gwangmyeong, Daejeon and Dongdaegu -- four legs.
    ("Seoul-Busan KTX", 325.0, 4, 135.0),
    # Paris-Lyon TGV: about 1 h 57 published, 391 km great-circle, non-stop.
    ("Paris-Lyon TGV", 391.4891, 1, 117.0),
])
def test_the_shipped_high_speed_tier_tracks_published_timetables(name, km, legs, published_min):
    """Against the SHIPPED calibration, not the test one.

    This is the assertion that would notice the tier speeds being reverted or
    mistyped: at the old 75 km/h a non-stop Paris-Lyon comes out at 381 min
    against a published 117, a ratio of 3.3.
    """
    shipped = rail.load_rail_calibration()
    t = shipped.tiers["high_speed"]
    modelled = legs * t.stop_overhead_min + 60.0 * km * shipped.detour_factor / t.speed_kmh
    ratio = modelled / published_min
    assert 1 / HIGH_SPEED_TWO_SIGMA <= ratio <= HIGH_SPEED_TWO_SIGMA, (
        f"{name}: modelled {modelled:.0f} min against a published {published_min:.0f} "
        f"(ratio {ratio:.2f}); the fit's two-sigma band is "
        f"{1 / HIGH_SPEED_TWO_SIGMA:.2f} to {HIGH_SPEED_TWO_SIGMA:.2f}")
