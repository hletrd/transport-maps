"""Flights round closed airspace (graph/airspace.py) and who may cross it.

The closed areas here are boxes, not Natural Earth's countries, so the test
needs no download and says exactly what is closed: a "RUS" box over Siberia
and a "UKR" box over the Black Sea's north shore.
"""

from __future__ import annotations

import h3
import polars as pl
import pytest
import shapely

from transport_maps.graph import air, airspace, build
from transport_maps.sources import routes

RUS = shapely.box(40.0, 45.0, 140.0, 75.0)       # lon/lat
UKR = shapely.box(22.0, 44.0, 40.0, 52.0)
ICN, CDG, IST, KBP_EAST = (37.46, 126.44), (49.01, 2.55), (41.26, 28.74), (48.0, 45.0)


@pytest.fixture(scope="module")
def grid():
    return airspace.Grid([RUS, UKR], ["RUS", "UKR"])


def test_a_restricted_flight_goes_round_and_an_overflying_one_does_not(grid):
    """ICN-CDG crosses the "RUS" box. A restricted airline flies round it --
    longer than the great circle, and every leg checked clear -- while an
    airline that may overfly flies the great circle (absent from the result).

    Mutations performed and reverted, each RED: give overfly pairs the
    restricted set (CDG-ICN detoured); return the corridor without pulling it
    taut (`_pulled_km` -> the sum of cell-centre hops: over the bound below).
    """
    from scipy.sparse.csgraph import dijkstra

    gc = h3.great_circle_distance(ICN, CDG, unit="km")
    out = airspace.detoured_km(grid, [("ICN", "CDG", ICN, CDG, False),
                                      ("CDG", "ICN", CDG, ICN, True)])
    assert set(out) == {("ICN", "CDG")}
    # Longer than the great circle it may not fly, and shorter than the
    # cell-to-cell corridor it was pulled taut from.
    i = grid.index[h3.latlng_to_cell(*ICN, airspace.GRID_RES)]
    j = grid.index[h3.latlng_to_cell(*CDG, airspace.GRID_RES)]
    corridor = dijkstra(grid.graphs["restricted"][0], indices=i)[j]
    assert gc < out[("ICN", "CDG")] < 0.98 * corridor


def test_ukraine_is_closed_to_every_airline(grid):
    """IST to a point east of the "UKR" box crosses it: detoured even for an
    airline that may overfly Russia (its path round may not use the RUS box
    either way, since the overfly set is UKR alone)."""
    out = airspace.detoured_km(grid, [("IST", "XXX", IST, KBP_EAST, True)])
    assert out[("IST", "XXX")] > h3.great_circle_distance(IST, KBP_EAST, unit="km")


def test_an_airline_serving_russia_may_overfly_it_and_an_unnamed_one_is_no_evidence():
    """The route data's own evidence: Air China flies PEK-SVO, so it may cross
    Russia on PEK-CDG; Lufthansa serves nothing there; Air India is a
    documented overflier (OVERFLY_ALSO); an airline cell left blank says
    nothing.

    Mutation performed and reverted: drop the `serving` set -> RED (PEK-CDG
    read as restricted)."""
    country = {"PEK": "CN", "SVO": "RU", "CDG": "FR", "FRA": "DE", "DEL": "IN", "EWR": "US",
               "ICN": "KR"}
    airlines = {("PEK", "SVO"): {"air_china"}, ("PEK", "CDG"): {"air_china", "air_france"},
                ("FRA", "ICN"): {"lufthansa", "korean_air"}, ("DEL", "EWR"): {"air_india"},
                ("CDG", "ICN"): {""}}
    pairs = set(airlines)
    over = routes.overfly(pairs, airlines, country)
    assert over == {("PEK", "SVO"): True, ("PEK", "CDG"): True, ("FRA", "ICN"): False,
                    ("DEL", "EWR"): True, ("CDG", "ICN"): False}


def test_the_flight_edge_carries_the_detoured_block_time(monkeypatch, grid):
    """`_air_edges` prices a restricted flight on the distance flown round
    closed airspace, and an overflying one on the great circle.

    Mutation performed and reverted: `flown.get((src, dst), d)` -> `d` -> RED.
    """
    from transport_maps import config
    from transport_maps.graph.nodes import NodeIndex
    from transport_maps.sources import countries

    apts = [("ICN", *ICN, "large", "KR"), ("CDG", *CDG, "large", "FR")]
    monkeypatch.setattr(build.airports, "scheduled_airports", lambda: pl.DataFrame(
        apts, schema=["iata", "lat", "lon", "size", "country"], orient="row"))
    monkeypatch.setattr(build.routes, "route_network", lambda: pl.DataFrame(
        [("ICN", "CDG", False), ("CDG", "ICN", True)],
        schema=["src", "dst", "overfly"], orient="row"))
    monkeypatch.setattr(countries, "_polygons", lambda: ([RUS, UKR], ["RUS", "UKR"]))
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for _, la, lo, *_ in apts]
    iatas = [a[0] for a in apts]
    idx = NodeIndex(cells=cells, airports=iatas,
                    _cell_pos={c: i for i, c in enumerate(cells)},
                    _airport_pos={a: len(cells) + i for i, a in enumerate(iatas)},
                    _airport_cell={a: i for i, a in enumerate(iatas)})
    rows, cols, w = build._air_edges(idx)
    edge = {(int(r), int(c)): float(x) for r, c, x in zip(rows, cols, w)}
    cal = air.load_calibration()
    gc = h3.great_circle_distance(ICN, CDG, unit="km")
    flown = airspace.detoured_km(grid, [("ICN", "CDG", ICN, CDG, False)])[("ICN", "CDG")]
    border = cal.border_min["large"]
    assert edge[(idx.airport_index("ICN"), idx.airport_intl_arr_index("CDG"))] == \
        air.block_time_min(flown, "large", "large", cal) + border
    assert edge[(idx.airport_index("CDG"), idx.airport_intl_arr_index("ICN"))] == \
        air.block_time_min(gc, "large", "large", cal) + border


def test_the_turns_a_detour_returns_are_a_clear_path_of_its_length(grid):
    """The page draws a detoured flight through the turns airspace.json holds
    (emit/airspace_json.py). Airport -> turns -> airport must be a path that
    never crosses the closed area and whose length is the distance the flight
    is timed on; an overflying pair returns none.

    Mutation performed and reverted: record the corridor's cell centres
    instead of the taut path's turns -> RED (longer than the flown distance).
    """
    paths: dict = {}
    out = airspace.detoured_km(grid, [("ICN", "CDG", ICN, CDG, False),
                                      ("CDG", "ICN", CDG, ICN, True)], paths)
    assert set(paths) == {("ICN", "CDG")} and paths[("ICN", "CDG")]
    pts = [ICN, *paths[("ICN", "CDG")], CDG]
    length = sum(h3.great_circle_distance(pts[k], pts[k + 1], unit="km")
                 for k in range(len(pts) - 1))
    assert length == pytest.approx(out[("ICN", "CDG")], rel=0.002)
    for k in range(len(pts) - 1):
        assert not airspace._crosses(grid.closed_restricted, pts[k], pts[k + 1]), (pts[k], pts[k + 1])
