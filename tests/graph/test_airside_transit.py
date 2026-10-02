"""Border control is paid per zone ENTERED, not per flight that crosses one (A15).

`build_graph` is run for real on eight airports and a one-span "ground"
between Narita and Haneda; only the airport table and the route network are
stubbed. Each journey is solved with scipy, as the build solves it, and its
time is compared with the sum of its parts worked out by hand from the
calibration file -- never read back off the graph under test -- so the number
of border charges in it is counted, not assumed:

    ICN -> NRT -> FRA   airside transit at Narita             one border
    ICN -> NRT -> CTS   enters Japan at Narita, flies on      one border
    ICN -> NRT, by road to HND, HND -> CDG
                        a LANDSIDE connection: enters Japan,  two borders
                        then leaves it again
    ICN -> LAX -> MEX   the US has no airside transit         two borders
    ICN -> NRT          a nonstop flight, as before           one border

Before A15 the first and second rows' figures were the same, but the first
paid 45 minutes twice.
"""

from __future__ import annotations

import h3
import numpy as np
import polars as pl
import pytest
from scipy.sparse.csgraph import dijkstra

from transport_maps import config
from transport_maps.graph import air, build, transfers
from transport_maps.graph.nodes import NodeIndex

# iata, lat, lon, size, country (OurAirports), Natural Earth A3 of its cell
AIRPORTS = [
    ("ICN", 37.4602, 126.4407, "large", "KR", "KOR"),
    ("NRT", 35.7720, 140.3929, "large", "JP", "JPN"),
    ("HND", 35.5494, 139.7798, "large", "JP", "JPN"),
    ("CTS", 42.7752, 141.6923, "large", "JP", "JPN"),
    ("FRA", 50.0379, 8.5622, "large", "DE", "DEU"),
    ("CDG", 49.0097, 2.5479, "large", "FR", "FRA"),
    ("LAX", 33.9416, -118.4085, "large", "US", "USA"),
    ("MEX", 19.4363, -99.0721, "large", "MX", "MEX"),
]
# NRT -> ICN is there for its frequency: it brings Narita's median onward
# wait under the minimum connection time, so the airside connection (75 min)
# is cheaper than walking out and checking in again (30 + 70) and the
# journeys below really do transit airside. Without it the connection costs
# the long-haul wait, the landside way round wins (B1 in the build plan), and
# the airside rule is never exercised.
ROUTES = [("ICN", "NRT"), ("NRT", "FRA"), ("NRT", "CTS"), ("NRT", "ICN"), ("HND", "CDG"),
          ("ICN", "LAX"), ("LAX", "MEX")]
ZONE = {"KOR": "KR", "JPN": "JP", "DEU": "SCHENGEN", "FRA": "SCHENGEN",
        "USA": "US", "MEX": "MX"}
ROAD_NRT_HND = 90.0
META = {a[0]: a[1:] for a in AIRPORTS}
CAL = air.load_calibration()


@pytest.fixture
def solved(monkeypatch):
    """Minutes from Incheon's cell to every node, and the index."""
    monkeypatch.setattr(build.airports, "scheduled_airports", lambda: pl.DataFrame(
        [a[:5] for a in AIRPORTS], schema=["iata", "lat", "lon", "size", "country"],
        orient="row"))
    monkeypatch.setattr(build.routes, "route_network", lambda: pl.DataFrame(
        ROUTES, schema=["src", "dst"], orient="row"))
    cells = [h3.latlng_to_cell(lat, lon, config.SOLVE_RES) for _, lat, lon, *_ in AIRPORTS]
    assert len(set(cells)) == len(cells)
    iatas = [a[0] for a in AIRPORTS]
    pos = {a: i for i, a in enumerate(iatas)}
    idx = NodeIndex(cells=cells, airports=iatas,
                    _cell_pos={c: i for i, c in enumerate(cells)},
                    _airport_pos={a: len(cells) + i for i, a in enumerate(iatas)},
                    _airport_cell=dict(pos),
                    # The one piece of ground: a road between the two Tokyo
                    # airports, which are cells apart (graph/landmass spans).
                    spans={(pos["NRT"], pos["HND"]): ROAD_NRT_HND,
                           (pos["HND"], pos["NRT"]): ROAD_NRT_HND})
    country = np.array([a[5] for a in AIRPORTS])
    zone = np.array([ZONE[c] for c in country])
    csr = build.build_graph(idx, country=country, zone=zone,
                            speeds=np.full(len(cells), 60.0))
    assert csr.shape == (idx.n, idx.n)
    return dijkstra(csr, directed=True, indices=pos["ICN"]), idx


def _km(a, b):
    return h3.great_circle_distance(META[a][:2], META[b][:2], unit="km")


def _block(a, b):
    return air.block_time_min(_km(a, b), META[a][2], META[b][2], CAL)


def _conn(at):
    """max(MCT, median expected wait of the airport's onward services)."""
    waits = [air.expected_wait_min(air.frequency_model(META[at][2], META[d][2], _km(at, d), CAL))
             for s, d in ROUTES if s == at]
    return max(CAL.connection_min[META[at][2]], float(np.median(waits)))


PROC, OUT, BORDER = (CAL.processing_min["large"], CAL.disembark_min["large"],
                     CAL.border_min["large"])


def _at(minutes, idx, iata):
    return minutes[idx.airport_cell_index(iata)]


def test_a_nonstop_international_flight_pays_the_border_once(solved):
    minutes, idx = solved
    assert _at(minutes, idx, "NRT") == pytest.approx(PROC + _block("ICN", "NRT") + BORDER + OUT)


def test_an_airside_transit_pays_the_border_once(solved):
    """Seoul -> Narita -> Frankfurt: emigration at Incheon, immigration at
    Frankfurt, nothing at Narita. The pre-A15 graph charged both flights.

    Mutations performed and reverted, each -> red: charge the border on the
    international layer's flights too; connect the international arrival to
    the DOMESTIC departure everywhere; land a crossing flight on the domestic
    arrival node.
    """
    minutes, idx = solved
    assert _conn("NRT") < OUT + PROC, "fixture lost the airside regime"
    one = PROC + _block("ICN", "NRT") + _conn("NRT") + _block("NRT", "FRA") + OUT
    assert _at(minutes, idx, "FRA") == pytest.approx(one + BORDER)
    assert _at(minutes, idx, "FRA") != pytest.approx(one + 2 * BORDER)


def test_entering_a_zone_airside_and_flying_on_inside_it_pays_once(solved):
    """Seoul -> Narita -> Sapporo: the border is Japan's, paid on the flight
    into Narita; the domestic hop adds nothing and is not let off it either.

    Mutation performed and reverted: put no border on a first crossing
    (CTS one border short) -> red.
    """
    minutes, idx = solved
    want = PROC + _block("ICN", "NRT") + BORDER + _conn("NRT") + _block("NRT", "CTS") + OUT
    assert _at(minutes, idx, "CTS") == pytest.approx(want)


def test_a_landside_connection_enters_the_zone_and_pays_again_to_leave(solved):
    """Narita to Haneda by road is an entry into Japan; flying on from
    Haneda is a new crossing. Two borders, as two passport desks.

    Mutation performed and reverted: give the access edge a way into the
    international departure node, so a traveller who has been landside keeps
    the border already paid -> red.
    """
    minutes, idx = solved
    want = (PROC + _block("ICN", "NRT") + BORDER + OUT + ROAD_NRT_HND
            + PROC + _block("HND", "CDG") + BORDER + OUT)
    assert _at(minutes, idx, "CDG") == pytest.approx(want)


def test_a_connection_in_a_zone_without_airside_transit_pays_twice(solved):
    """Every passenger from abroad is admitted at a US airport, connecting or
    not (transfers.NO_AIRSIDE_TRANSIT), so Seoul -> Los Angeles -> Mexico City
    pays the US border and then Mexico's -- the figure the pre-A15 graph
    gave, kept.

    Mutation performed and reverted: empty NO_AIRSIDE_TRANSIT -> red (one
    border short).
    """
    minutes, idx = solved
    assert not transfers.airside_transit("US")
    want = (PROC + _block("ICN", "LAX") + BORDER + _conn("LAX") + _block("LAX", "MEX")
            + BORDER + OUT)
    assert _at(minutes, idx, "MEX") == pytest.approx(want)
